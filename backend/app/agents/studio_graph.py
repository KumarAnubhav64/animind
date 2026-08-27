"""Studio graph: Writer -> Director -> Producer, with revision loop.

Writer structures the explanation, Director storyboards it, Producer reviews
feasibility; rejected storyboards go back to the Director (max 2 revisions).
"""

import asyncio
import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.llm import fallback_llm, planner_llm
from app.config import get_settings
from app.pipeline.telemetry import record as _record_call
from app.prompts.director import (
    DIRECTOR_SYSTEM_PROMPT,
    director_revision_prompt,
    director_user_prompt,
)
from app.prompts.producer import FeasibilityReport, PRODUCER_SYSTEM_PROMPT
from app.prompts.writer import ScriptOutline, WRITER_SYSTEM_PROMPT
from app.schemas import Storyboard
from app.pipeline.events import publish

logger = logging.getLogger("animind.studio")

MAX_REVISIONS = 2


async def structured_call(
    model, messages, schema, attempts: int = 3, project_id: str | None = None
):
    """Invoke with_structured_output with retries (json_schema method; Groq's
    tool-call method fails on nested schemas, and long generations occasionally
    emit invalid JSON)."""
    structured = model.with_structured_output(schema, method="json_schema")
    model_name = getattr(model, "model_name", None) or getattr(model, "model", None) or str(model)
    last_err: Exception | None = None
    for i in range(attempts):
        start = asyncio.get_event_loop().time()
        try:
            result = await structured.ainvoke(messages)
            _record_call(
                model=model_name, result=result,
                latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                project_id=project_id,
            )
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            message = str(e).lower()
            if "tokens per day" in message or "tpd" in message:
                fallback = fallback_llm().with_structured_output(
                    schema, method="json_schema"
                )
                logger.warning(
                    "primary model hit daily token cap; switching to fallback model %s",
                    get_settings().fallback_model,
                )
                try:
                    result = await fallback.ainvoke(messages)
                    _record_call(
                        model=get_settings().fallback_model, result=result,
                        latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                        project_id=project_id, note="tpd-fallback",
                    )
                    return result
                except Exception as fallback_error:  # noqa: BLE001
                    last_err = fallback_error
                    logger.warning("fallback structured call failed: %s", fallback_error)
                    raise fallback_error
            logger.warning("structured call failed (attempt %s/%s): %s", i + 1, attempts, e)
    raise last_err  # type: ignore[misc]


class StudioState(TypedDict):
    project_id: str | None
    topic: str
    audience_level: str
    subject: str | None
    outline: dict | None
    storyboard: dict | None
    issues: list[str]
    revisions: int
    approved: bool


async def write_node(state: StudioState) -> dict[str, Any]:
    subject = f"\nSubject: {state['subject']}" if state["subject"] else ""
    outline = await structured_call(
        planner_llm(),
        [
            ("system", WRITER_SYSTEM_PROMPT),
            ("human", f"Topic: {state['topic']}\nAudience level: {state['audience_level']}{subject}"),
        ],
        ScriptOutline,
        project_id=state.get("project_id"),
    )
    logger.info("writer outline: %s ideas", len(outline.key_ideas))
    if state.get("project_id"):
        await publish(state["project_id"], {"type": "workflow", "agent": "Writer", "node": "write", "message": f"Outlined {len(outline.key_ideas)} teaching ideas from intuition to formalism.", "details": {"ideas": len(outline.key_ideas)}})
    return {"outline": outline.model_dump()}


async def direct_node(state: StudioState) -> dict[str, Any]:
    if state["issues"]:
        prompt = director_revision_prompt(
            json.dumps(state["storyboard"], indent=2), state["issues"]
        )
    else:
        prompt = director_user_prompt(
            json.dumps(state["outline"], indent=2),
            state["topic"],
            state["audience_level"],
            state["subject"],
        )
    storyboard = await structured_call(
        planner_llm(),
        [("system", DIRECTOR_SYSTEM_PROMPT), ("human", prompt)],
        Storyboard,
        project_id=state.get("project_id"),
    )
    logger.info("director storyboard: %s scenes (revision %s)", len(storyboard.scenes), state["revisions"])
    if state.get("project_id"):
        await publish(state["project_id"], {"type": "workflow", "agent": "Director", "node": "direct", "message": f"Mapped the explanation into {len(storyboard.scenes)} scenes with explicit visual intent.", "details": {"scenes": len(storyboard.scenes), "revision": state["revisions"]}})
    return {"storyboard": storyboard.model_dump(), "issues": []}


async def review_node(state: StudioState) -> dict[str, Any]:
    report = await structured_call(
        planner_llm(),
        [
            ("system", PRODUCER_SYSTEM_PROMPT),
            ("human", json.dumps(state["storyboard"], indent=2)),
        ],
        FeasibilityReport,
        project_id=state.get("project_id"),
    )
    logger.info("producer: approved=%s issues=%s", report.approved, len(report.issues))
    if state.get("project_id"):
        await publish(state["project_id"], {"type": "workflow", "agent": "Producer", "node": "review", "message": "Storyboard approved for production." if report.approved else f"Storyboard needs revision: {len(report.issues)} issue(s).", "details": {"approved": report.approved, "issues": report.issues}})
    return {"approved": report.approved, "issues": report.issues}


def after_review(state: StudioState) -> str:
    settings = get_settings()
    if state["approved"] or state["revisions"] >= settings.max_storyboard_revisions:
        return END
    return "revise"


def revise_node(state: StudioState) -> dict[str, Any]:
    return {"revisions": state["revisions"] + 1}


def build_studio_graph():
    g = StateGraph(StudioState)
    g.add_node("write", write_node)
    g.add_node("direct", direct_node)
    g.add_node("review", review_node)
    g.add_node("revise", revise_node)

    g.set_entry_point("write")
    g.add_edge("write", "direct")
    g.add_edge("direct", "review")
    g.add_conditional_edges("review", after_review, {"revise": "revise", END: END})
    g.add_edge("revise", "direct")
    return g.compile()


STUDIO_GRAPH = build_studio_graph()


async def run_studio(topic: str, audience_level: str, subject: str | None, project_id: str | None = None) -> Storyboard:
    final = await STUDIO_GRAPH.ainvoke(
        {
            "topic": topic,
            "project_id": project_id,
            "audience_level": audience_level,
            "subject": subject,
            "outline": None,
            "storyboard": None,
            "issues": [],
            "revisions": 0,
            "approved": False,
        }
    )
    return Storyboard(**final["storyboard"])
