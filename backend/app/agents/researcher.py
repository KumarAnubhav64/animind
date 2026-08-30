"""Researcher agent: gathers web sources on the topic and distills a research
brief that the Writer and Director use to ground the explanation.

The brief is deliberately compact: 3-5 concrete, citable facts/analogies that
make the teaching arc accurate and concrete. It never blocks the pipeline —
if search or the LLM call fails, the brief is empty and the Writer proceeds
on its own.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.llm import planner_llm
from app.agents.structured import structured_call
from app.config import get_settings
from app.pipeline.events import publish
from app.tools.websearch import search_multi

logger = logging.getLogger("animind.research")

RESEARCH_SYSTEM_PROMPT = """\
You are the researcher for an educational animation studio in the style of \
3Blue1Brown. You receive the video topic, audience level, and a handful of web \
search snippets about it.

Your job: produce a RESEARCH BRIEF that helps the writer build an accurate, \
concrete explanation. Include:
- key_facts: 3-5 concrete, correct facts about the topic that an explanation \
must get right (from the snippets; never invent facts the snippets do not support).
- analogies: 1-3 concrete analogies or everyday metaphors from the snippets \
(ideally with a short visual idea) that make the abstract idea tangible.
- misconceptions: 1-3 common misconceptions learners hold about this topic.
- sources: the URLs actually used, with a one-line note on what each is good for.

Rules:
- If a snippet contradicts another, prefer the majority/reputable source and \
note the disagreement.
- Keep every fact short and citable. No speculation, no filler.
- The brief is fed to the Writer: prefer facts that suggest HOW to teach, not \
just WHAT is true.
"""


class ResearchBrief(BaseModel):
    key_facts: list[str] = Field(
        default_factory=list,
        description="3-5 concrete facts the explanation must get right",
    )
    analogies: list[str] = Field(
        default_factory=list,
        description="1-3 analogies/metaphors (with a visual idea) that make it tangible",
    )
    misconceptions: list[str] = Field(
        default_factory=list,
        description="1-3 common learner misconceptions",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="URLs actually used, each with a one-line note",
    )


def _build_queries(topic: str, subject: str | None) -> list[str]:
    base = f"{topic} explained simply" if subject else f"{topic} explained"
    return [
        base,
        f"{topic} intuition analogy",
        f"{topic} common misconception",
    ]


def _format_snippets(snippets: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for i, item in enumerate(snippets, start=1):
        lines.append(
            f"[{i}] {item['title']}\n"
            f"    URL: {item['href']}\n"
            f"    {item['body']}"
        )
    return "\n\n".join(lines)


def brief_to_text(brief: dict[str, Any] | ResearchBrief | None) -> str:
    """Render a ResearchBrief as compact markdown for Writer/Director prompts."""
    if not brief:
        return ""
    data = brief if isinstance(brief, dict) else brief.model_dump()
    parts: list[str] = []
    if data.get("key_facts"):
        parts.append("Facts to get right:\n" + "\n".join(f"- {f}" for f in data["key_facts"]))
    if data.get("analogies"):
        parts.append("Useful analogies:\n" + "\n".join(f"- {a}" for a in data["analogies"]))
    if data.get("misconceptions"):
        parts.append("Common misconceptions:\n" + "\n".join(f"- {m}" for m in data["misconceptions"]))
    if data.get("sources"):
        parts.append("Sources:\n" + "\n".join(f"- {s}" for s in data["sources"]))
    return "\n\n".join(parts)


async def research_topic(
    topic: str,
    audience_level: str,
    subject: str | None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Search the web for the topic and distill a ResearchBrief.

    Never raises: any failure returns an empty brief so production continues.
    """
    settings = get_settings()
    if project_id:
        await publish(
            project_id,
            {
                "type": "workflow",
                "agent": "Researcher",
                "node": "research",
                "message": f"Searching the web for concrete facts on '{topic}'.",
                "details": {},
            },
        )

    queries = _build_queries(topic, subject)
    snippets = search_multi(queries, per_query=settings.research_results_per_query)
    if not snippets:
        logger.warning("researcher: no web results for %r — brief will be empty", topic)
        if project_id:
            await publish(
                project_id,
                {
                    "type": "workflow",
                    "agent": "Researcher",
                    "node": "research",
                    "message": "Web search returned no usable results; proceeding without external research.",
                    "details": {},
                },
            )
        return {}

    human = (
        f"Topic: {topic}\n"
        f"Audience level: {audience_level}\n"
        f"Subject: {subject or 'general'}\n\n"
        f"Web search snippets:\n{_format_snippets(snippets)}\n\n"
        "Produce the research brief JSON now."
    )
    try:
        brief = await structured_call(
            planner_llm(),
            [("system", RESEARCH_SYSTEM_PROMPT), ("human", human)],
            ResearchBrief,
            project_id=project_id,
        )
    except Exception as error:  # noqa: BLE001
        logger.warning("researcher: brief summarization failed: %s", error)
        return {}

    logger.info(
        "researcher: brief for %r — %s facts, %s analogies, %s misconceptions, %s sources",
        topic,
        len(brief.key_facts),
        len(brief.analogies),
        len(brief.misconceptions),
        len(brief.sources),
    )
    if project_id:
        await publish(
            project_id,
            {
                "type": "workflow",
                "agent": "Researcher",
                "node": "research",
                "message": f"Gathered {len(brief.key_facts)} facts and {len(brief.analogies)} analogies to ground the explanation.",
                "details": {"facts": len(brief.key_facts), "analogies": len(brief.analogies)},
            },
        )
    return brief.model_dump()
