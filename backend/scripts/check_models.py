"""Health check: probe every configured model endpoint and report OK/FAIL.

Runs a tiny, cheap call against each model the pipeline actually uses and prints
a table. Useful after config changes, when daily caps are suspected, or when QA
(Vision Critic) seems to be passing everything silently.

Usage:
    uv run python scripts/check_models.py            # text-only probes (fast)
    uv run python scripts/check_models.py --tts      # also probe TTS synthesis
    uv run python scripts/check_models.py --verbose  # show full error detail
    uv run python scripts/check_models.py --timeout 45

Exit code is 0 only if every probe that ran succeeded. Probes are fail-safe:
an exception is reported as FAIL, never raised out of the harness.
"""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groq import Groq  # noqa: E402

from app.agents.llm import _backup_groq, _groq, fallback_llm  # noqa: E402
from app.config import get_settings  # noqa: E402

PROBE_SYSTEM = "You are a connectivity probe."
PROBE_HUMAN = "Reply with exactly the single word: ok"
PROBE_HUMAN_JSON = 'Reply with exactly this JSON object: {"ok": true}'


@dataclass
class ProbeResult:
    name: str
    model: str
    provider: str
    ok: bool = False
    latency_ms: int = 0
    detail: str = ""
    note: str = ""


def _err_detail(exc: Exception) -> str:
    msg = " ".join(str(exc).split())
    if not msg:
        return type(exc).__name__
    if "tokens per day" in msg.lower() or "tpd" in msg.lower():
        return "DAILY CAP: " + msg[:160]
    if "insufficient_user_quota" in msg.lower():
        return "QUOTA/403: " + msg[:160]
    if "rate_limit" in msg.lower() or "429" in msg:
        return "RATE LIMITED: " + msg[:160]
    return msg[:220]


async def _probe_chat(llm, name: str, model: str, provider: str, timeout: float) -> ProbeResult:
    res = ProbeResult(name=name, model=model, provider=provider)
    start = time.monotonic()
    try:
        await asyncio.wait_for(
            llm.ainvoke([("system", PROBE_SYSTEM), ("human", PROBE_HUMAN)]),
            timeout=timeout,
        )
        res.ok = True
    except asyncio.TimeoutError:
        res.detail = f"timed out after {timeout:.0f}s"
    except Exception as e:  # noqa: BLE001
        res.detail = _err_detail(e)
    res.latency_ms = int((time.monotonic() - start) * 1000)
    return res


async def _probe_tts(timeout: float) -> ProbeResult:
    s = get_settings()
    res = ProbeResult(name="tts", model=s.tts_model, provider="groq")
    start = time.monotonic()
    try:
        def call():
            client = Groq(api_key=s.groq_api_key)
            return client.audio.speech.create(
                model=s.tts_model, voice=s.tts_voice, input="ok", response_format="mp3"
            ).read()

        await asyncio.wait_for(asyncio.to_thread(call), timeout=timeout)
        res.ok = True
    except asyncio.TimeoutError:
        res.detail = f"timed out after {timeout:.0f}s"
    except Exception as e:  # noqa: BLE001
        res.detail = _err_detail(e)
    res.latency_ms = int((time.monotonic() - start) * 1000)
    return res


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts", action="store_true", help="also probe TTS synthesis")
    parser.add_argument("--verbose", action="store_true", help="show full error detail")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-probe timeout (s)")
    args = parser.parse_args()

    s = get_settings()
    probes: list[ProbeResult] = []
    no_key = "no ANIMIND_GROQ_API_KEY set"

    # -- Groq text models (primary key) -----------------------------------
    for name, model in (
        ("planner", s.planner_model),
        ("coder", s.coder_model),
        ("fixer", s.fixer_model),
        ("fallback", s.fallback_model),
    ):
        if not s.groq_api_key:
            probes.append(ProbeResult(name=name, model=model, provider="groq", detail=no_key))
            continue
        probes.append(await _probe_chat(_groq(model, 0.3), name, model, "groq", args.timeout))

    # -- Backup Groq key (used on 429 / daily-cap rotation) ---------------
    if s.groq_api_key_backup:
        probes.append(
            await _probe_chat(
                _backup_groq(s.coder_model, 0.3), "coder@backup-key", s.coder_model, "groq-backup", args.timeout
            )
        )
    else:
        probes.append(ProbeResult(name="coder@backup-key", model="(unset)", provider="groq-backup", detail="no backup key configured", ok=True))

    # -- TTS ----------------------------------------------------------------
    if args.tts:
        probes.append(await _probe_tts(args.timeout))
    else:
        probes.append(
            ProbeResult(name="tts", model=s.tts_model, provider="groq", detail="skipped (pass --tts)", ok=True)
        )

    # -- AgentRouter models (vision + optional premium/math-expert) ---------
    async def router_probe(name: str, model: str | None, timeout: float) -> ProbeResult:
        if not model:
            return ProbeResult(name=name, model="(unset)", provider="router", detail="not configured", ok=True)
        if not s.router_api_key:
            return ProbeResult(name=name, model=model, provider="router", detail="no ANIMIND_ROUTER_API_KEY", ok=False)
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=model,
            api_key=s.router_api_key,
            base_url=s.router_base_url,
            temperature=0.0,
            timeout=int(args.timeout),
            max_retries=1,
            default_headers={"User-Agent": "opencode/1.0.0"},
        )
        return await _probe_chat(llm, name, model, "router", timeout)

    if s.vision_critique:
        probes.append(await router_probe("vision", s.vision_model, args.timeout))
    else:
        probes.append(ProbeResult(name="vision", model=s.vision_model, provider="router", detail="vision_critique disabled", ok=True))

    # -- Groq vision fallback (used when the primary vision model is down) --
    if s.vision_model_fallback:
        if not s.groq_api_key:
            probes.append(ProbeResult(name="vision@fallback", model=s.vision_model_fallback, provider="groq", detail=no_key))
        else:
            from langchain_groq import ChatGroq

            fallback_vision = ChatGroq(
                model=s.vision_model_fallback,
                api_key=s.groq_api_key,
                temperature=0.0,
                max_retries=1,
                timeout=int(args.timeout),
            )
            probes.append(await _probe_chat(fallback_vision, "vision@fallback", s.vision_model_fallback, "groq", args.timeout))
    else:
        probes.append(ProbeResult(name="vision@fallback", model="(unset)", provider="groq", detail="no fallback configured", ok=True))
    math_model = s.math_expert_model or s.premium_model
    if s.math_expert_enabled and math_model:
        probes.append(await router_probe("math_expert", math_model, args.timeout))
    if s.premium_model and s.premium_repair_enabled:
        probes.append(await router_probe("premium", s.premium_model, args.timeout))

    # -- Report --------------------------------------------------------------
    name_w = max(len(p.name) for p in probes)
    model_w = max(len(p.model) for p in probes)
    print("\nANIMIND MODEL HEALTH CHECK\n" + "-" * (name_w + model_w + 42))
    all_ok = True
    for p in probes:
        status = "OK  " if p.ok else "FAIL"
        detail = p.detail if (p.detail and (args.verbose or not p.ok)) else p.note
        extra = f" ({p.latency_ms}ms)" if p.ok else ""
        print(f"  [{status}] {p.name:<{name_w}} {p.model:<{model_w}} {p.provider:<12}{extra} {detail}".rstrip())
        all_ok = all_ok and p.ok
    print("-" * (name_w + model_w + 42))
    print(f"Result: {'ALL PROBES OK' if all_ok else 'SOME PROBES FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
