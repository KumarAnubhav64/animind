from app.agents.llm import planner_llm
from app.prompts import PLANNER_SYSTEM_PROMPT
from app.schemas import Storyboard


async def generate_storyboard(
    topic: str, audience_level: str, subject: str | None
) -> Storyboard:
    subject_line = f"\nSubject area: {subject}" if subject else ""
    user = (
        f"Topic: {topic}\n"
        f"Audience level: {audience_level}{subject_line}\n\n"
        "Produce the storyboard JSON now."
    )
    structured = planner_llm().with_structured_output(
        Storyboard, method="json_schema"
    )
    result = await structured.ainvoke(
        [
            ("system", PLANNER_SYSTEM_PROMPT),
            ("human", user),
        ]
    )
    return result
