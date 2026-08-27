"""Deterministic treatment markdown generator.

Builds a human-readable scene treatment from the compiled SceneSpec +
narration + audio duration.  No LLM calls — purely derived from data.
"""

from __future__ import annotations

from typing import Any

from app.schemas.spec import SceneSpec


_BEAT_LABELS = [
    "Setup",
    "Build-up",
    "Development",
    "Transformation",
    "Climax",
    "Resolution",
    "Highlight",
    "Wrap-up",
]


def _action_summary(action: dict[str, Any]) -> str:
    """One-line description of a SpecAction."""
    op = action.get("op", "unknown")
    if op == "set_title":
        return f"Title: \"{action.get('text', '')}\""
    if op.startswith("add_"):
        kind = op.replace("add_", "")
        oid = action.get("id", "")
        pos = ""
        if action.get("at"):
            pos = f"at ({action['at'][0]:.1f}, {action['at'][1]:.1f})"
        elif action.get("region"):
            pos = f"in {action['region']}"
        color = f" ({action['color']})" if action.get("color") else ""
        extra = ""
        if action.get("text"):
            extra = f" text=\"{action['text'][:30]}\""
        elif action.get("tex"):
            extra = f" tex=\"{action['tex'][:30]}\""
        elif action.get("expr"):
            extra = f" expr={action['expr'][:30]}"
        elif action.get("shape"):
            extra = f" shape={action['shape']}"
        elif action.get("asset"):
            extra = f" asset={action['asset']}"
        scale = f" scale={action['scale']}" if action.get("scale") else ""
        return f"{kind} '{oid}'{color}{extra}{scale} {pos}".strip()
    if op == "animate":
        return f"animate {action.get('target', 'all')}: {action.get('anim', 'write')}"
    if op == "transform":
        oid = action.get("id", "")
        tex = action.get("tex") or action.get("text", "")
        return f"transform '{oid}' → {tex[:30]}"
    if op == "move":
        oid = action.get("id", "")
        sec = action.get("seconds", "")
        return f"move '{oid}' ({sec}s)" if sec else f"move '{oid}'"
    if op == "rotate":
        oid = action.get("id", "")
        turns = action.get("turns", 0)
        return f"rotate '{oid}' {turns:.1f} turns"
    if op == "pulse":
        return f"pulse {action.get('target', 'all')}"
    if op == "remove":
        return f"remove {action.get('target', 'all')}"
    if op == "wait":
        return f"wait {action.get('seconds', 1):.1f}s"
    if op == "connect":
        return f"connect '{action.get('id', '')}' {action.get('from_id', '')} → {action.get('to', '')}"
    if op == "label":
        return f"label '{action.get('id', '')}' on {action.get('target', '')} {action.get('direction', '')}"
    if op == "add_bars":
        vals = action.get("values", [])
        return f"bars '{action.get('id', '')}' values={vals}"
    if op == "add_axes":
        return f"axes '{action.get('id', '')}' x={action.get('x_range', [])} y={action.get('y_range', [])}"
    return f"{op} {action.get('id', '')}"


def _layout_diagram(spec: SceneSpec) -> str:
    """ASCII art layout from spec.layout regions."""
    if not spec.layout or not spec.layout.regions:
        return "(dynamic — derived from action coordinates)"
    regions = spec.layout.regions
    parts = ["┌─────────────────────────────────────────────┐"]
    parts.append("│                     MAIN                    │")
    if len(regions) == 1:
        r = regions[0]
        parts.append(f"│  ┌───────────────┐     {r['name'][:15]:<15} │")
        parts.append(f"│  │               │     {r.get('area', ''):<15} │")
        parts.append("│  └───────────────┘                         │")
    else:
        row = "│"
        for r in regions[:3]:
            label = r["name"][:14]
            area = r.get("area", "")
            row += f"  ┌{'─' * 14}┐"
        parts.append(row)
        row = "│"
        for r in regions[:3]:
            row += f"  │{r['name'][:14]:^14}│"
        parts.append(row)
        row = "│"
        for r in regions[:3]:
            row += f"  │{r.get('area', ''):^14}│"
        parts.append(row)
        row = "│"
        for _ in regions[:3]:
            row += "  └──────────────┘"
        parts.append(row)
    parts.append("├─────────────────────────────────────────────┤")
    parts.append("│  Caption area (y < -2.5)                    │")
    parts.append("└─────────────────────────────────────────────┘")
    return "\n".join(parts)


def _area_table(spec: SceneSpec) -> str:
    """Markdown table of area descriptions."""
    if not spec.layout or not spec.layout.regions:
        return "| Area | Content | Notes |\n|------|---------|-------|\n| Full | Derived from action coordinates | see beat actions |"
    rows = ["| Area | Content | Notes |", "|------|---------|-------|"]
    for r in spec.layout.regions:
        desc = r.description or f"{r.area} region"
        rows.append(f"| {r.name} | {desc} | {r.area} |")
    return "\n".join(rows)


def _generate_beat_name(index: int, actions: list[dict]) -> str:
    """Heuristic beat name from action types."""
    ops = {a.get("op", "") for a in actions}
    if "set_title" in ops:
        return "Title + opening"
    adds = {a.get("op", "").replace("add_", "") for a in actions if a.get("op", "").startswith("add_")}
    if any(a.get("op") == "animate" and "indicate" in str(a.get("anim", "")) for a in actions):
        return "Highlight"
    if any(a.get("op") == "transform" for a in actions):
        return "Transform"
    if any(a.get("op") == "rotate" for a in actions):
        return "Rotation / motion"
    if any(a.get("op") == "remove" for a in actions):
        return "Transition"
    if index < len(_BEAT_LABELS):
        return _BEAT_LABELS[index]
    return f"Beat {index + 1}"


def generate_treatment(
    title: str,
    narration: str,
    visual_description: str,
    spec_json: str | None,
    audio_duration: float | None = None,
) -> str:
    """Build the scene treatment markdown from compiled spec + context."""
    spec: SceneSpec | None = None
    if spec_json:
        try:
            spec = SceneSpec.model_validate_json(spec_json)
        except Exception:
            pass

    duration = audio_duration or 25.0
    beats = spec.beats if spec else []

    # --- Overview ---
    overview = (narration or visual_description or "").strip()
    if len(overview) > 300:
        overview = overview[:297] + "..."

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(overview)
    lines.append("")

    # --- Phases table ---
    if beats:
        lines.append("## Phases")
        lines.append("")
        lines.append("| # | Phase Name | Duration | Description |")
        lines.append("|---|-----------|----------|-------------|")
        total_actions = sum(len(b.actions) for b in beats)
        for i, beat in enumerate(beats):
            beat_actions = len(beat.actions) or 1
            beat_dur = duration * (beat_actions / max(total_actions, 1))
            beat_dur = max(beat_dur, 1.0)
            name = _generate_beat_name(i, [a.model_dump() for a in beat.actions])
            desc = beat.description or "; ".join(
                _action_summary(a.model_dump()) for a in beat.actions[:4]
            )
            if len(desc) > 120:
                desc = desc[:117] + "..."
            lines.append(f"| {i + 1} | {name} | ~{beat_dur:.1f}s | {desc} |")
        lines.append("")

    # --- Layout ---
    lines.append("## Layout")
    lines.append("")
    lines.append("```")
    lines.append(_layout_diagram(spec) if spec else "(no spec -- layout derived from codegen)")
    lines.append("```")
    lines.append("")

    # --- Area Descriptions ---
    if spec:
        lines.append("## Area Descriptions")
        lines.append("")
        lines.append(_area_table(spec))
        lines.append("")

    # --- Notes ---
    lines.append("## Notes")
    lines.append("")
    lines.append(f"- Total animation duration: ~{duration:.1f}s")
    lines.append("- Background: #1c1c1c (3Blue1Brown style)")
    lines.append("- Camera: static, fixed frame, centered")
    if spec and spec.layout and spec.layout.notes:
        lines.append(f"- Layout notes: {spec.layout.notes}")
    lines.append(f"- Narration word count: ~{len(narration.split())} words")
    lines.append("- Timing: paced to match narration audio")
    lines.append("")

    return "\n".join(lines)
