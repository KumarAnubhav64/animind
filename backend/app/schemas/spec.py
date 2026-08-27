"""SceneSpec: declarative scene format. The LLM describes beats; our compiler
emits the Manim code. This eliminates API hallucinations and layout bugs by
construction."""

from pydantic import BaseModel, ConfigDict, Field


class LayoutRegion(BaseModel):
    """A named spatial region in the scene with explicit coordinates."""
    model_config = ConfigDict(extra="ignore")

    name: str  # e.g. "circle_area", "sine_plot", "caption"
    area: str  # left|right|center|top|bottom|full
    description: str = ""  # what goes here
    at: list[float] | None = None  # explicit [x, y] center of region


class SceneLayout(BaseModel):
    """Spatial blueprint for the scene. The spec coder MUST define this before
    writing actions — it forces the LLM to think about WHERE things go before
    WHAT they are."""
    model_config = ConfigDict(extra="ignore")

    regions: list[LayoutRegion] = Field(
        description="Named spatial regions; actions will reference these by name"
    )
    notes: str = ""  # optional layout constraints or shared scale notes


class SpecAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    op: str  # validated leniently; the compiler ignores unknown ops
    id: str | None = None
    text: str | None = None
    tex: str | None = None
    shape: str | None = None  # circle|square|dot|triangle|diamond|ring|sphere|cube|cylinder|cone|torus
    asset: str | None = None  # pre-made asset: apple|car|building|earth|star|lightning|heart|checkmark|cross|person|gear|book
    color: str | None = None  # blue|red|green|yellow|teal|purple|orange|gold|white|grey|pink
    region: str | None = None  # center|left|right|top|bottom|top_left|top_right|bottom_left|bottom_right
    at: list[float] | None = None  # [x, y] in frame coords (-7..7, -4..4)
    scale: float | None = None
    target: str | None = None
    to: str | None = None  # connect endpoint
    anim: str | None = None
    seconds: float | None = None
    x_range: list[float] | None = None
    y_range: list[float] | None = None
    expr: str | None = None  # python lambda body in variable x, e.g. "x**2"
    direction: str | None = None  # up|down|left|right
    values: list[float] | None = None
    from_id: str | None = Field(default=None, alias="from")


class SpecBeat(BaseModel):
    description: str = Field(description="What is being said/shown in this beat")
    actions: list[SpecAction]


class SceneSpec(BaseModel):
    title: str
    layout: SceneLayout | None = None  # spatial blueprint (recommended)
    beats: list[SpecBeat] = Field(
        description="4-8 beats; each beat is one narration thought with its visual actions"
    )
