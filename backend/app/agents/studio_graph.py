"""Studio graph: Writer -> Director -> Producer, with revision loop.

Writer structures the explanation, Director storyboards it, Producer reviews
feasibility; rejected storyboards go back to the Director (max 2 revisions).
"""

import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.llm import planner_llm
from app.agents.structured import structured_call
from app.config import get_settings
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


class StudioState(TypedDict):
    project_id: str | None
    topic: str
    audience_level: str
    subject: str | None
    research_brief: dict | None
    outline: dict | None
    storyboard: dict | None
    issues: list[str]
    revisions: int
    approved: bool


async def research_node(state: StudioState) -> dict[str, Any]:
    settings = get_settings()
    if not settings.research_enabled:
        return {"research_brief": None}
    from app.agents.researcher import research_topic

    brief = await research_topic(
        state["topic"],
        state["audience_level"],
        state.get("subject"),
        project_id=state.get("project_id"),
    )
    if brief and state.get("project_id"):
        from app.db.repositories import project_repo

        project_repo.update(
            state["project_id"],
            research_brief=json.dumps(brief, ensure_ascii=False),
        )
    return {"research_brief": brief or None}


async def write_node(state: StudioState) -> dict[str, Any]:
    subject = f"\nSubject: {state['subject']}" if state["subject"] else ""
    from app.agents.researcher import brief_to_text

    research = brief_to_text(state.get("research_brief"))
    research_block = (
        f"\n\nWeb research brief (ground your outline in these — prefer the "
        f"analogies and correct any misconception):\n{research}"
        if research
        else ""
    )
    outline = await structured_call(
        planner_llm(),
        [
            ("system", WRITER_SYSTEM_PROMPT),
            ("human", f"Topic: {state['topic']}\nAudience level: {state['audience_level']}{subject}{research_block}"),
        ],
        ScriptOutline,
        project_id=state.get("project_id"),
    )
    logger.info("writer outline: %s ideas", len(outline.key_ideas))
    if state.get("project_id"):
        await publish(state["project_id"], {"type": "workflow", "agent": "Writer", "node": "write", "message": f"Outlined {len(outline.key_ideas)} teaching ideas from intuition to formalism.", "details": {"ideas": len(outline.key_ideas)}})
    return {"outline": outline.model_dump()}


async def direct_node(state: StudioState) -> dict[str, Any]:
    from app.agents.researcher import brief_to_text

    research = brief_to_text(state.get("research_brief"))
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
            research_brief=research,
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
    g.add_node("research", research_node)
    g.add_node("write", write_node)
    g.add_node("direct", direct_node)
    g.add_node("review", review_node)
    g.add_node("revise", revise_node)

    g.set_entry_point("research")
    g.add_edge("research", "write")
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
            "research_brief": None,
            "outline": None,
            "storyboard": None,
            "issues": [],
            "revisions": 0,
            "approved": False,
        }
    )
    return Storyboard(**final["storyboard"])
