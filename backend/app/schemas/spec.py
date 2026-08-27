"""SceneSpec: declarative scene format. The LLM describes beats; our compiler
emits the Manim code. This eliminates API hallucinations and layout bugs by
construction."""

from __future__ import annotations

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
    turns: float | None = None  # full rotations for rotate op (1.0 = one full turn)
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

    def validate_ids(self) -> list[str]:
        """Check that every object has an id and every reference points to a
        known id.  Returns a list of human-readable issue strings (empty =
        valid)."""
        issues: list[str] = []
        defined: set[str] = set()
        for bi, beat in enumerate(self.beats):
            for ai, action in enumerate(beat.actions):
                op = action.op
                # add_* ops MUST have an id
                if op.startswith("add_") and action.id:
                    defined.add(action.id)
                elif op.startswith("add_") and not action.id:
                    issues.append(
                        f"beat {bi + 1} action {ai + 1}: {op} is missing an 'id' — "
                        "every object must have an id so it can be referenced later"
                    )
                # connect needs both endpoints
                if op == "connect":
                    fid = action.from_id
                    tid = action.to
                    if not fid:
                        issues.append(
                            f"beat {bi + 1} action {ai + 1}: connect is missing 'from' "
                            "(the source object id)"
                        )
                    elif fid not in defined:
                        issues.append(
                            f"beat {bi + 1} action {ai + 1}: connect 'from' = "
                            f"'{fid}' but no object with that id has been defined yet"
                        )
                    if not tid:
                        issues.append(
                            f"beat {bi + 1} action {ai + 1}: connect is missing 'to' "
                            "(the target object id)"
                        )
                    elif tid not in defined:
                        issues.append(
                            f"beat {bi + 1} action {ai + 1}: connect 'to' = "
                            f"'{tid}' but no object with that id has been defined yet"
                        )
                # animate/rotate/move/transform/remove need a target or id
                if op in ("animate", "rotate", "move", "transform", "remove"):
                    ref = action.target or action.id
                    if not ref:
                        issues.append(
                            f"beat {bi + 1} action {ai + 1}: {op} has no 'target' "
                            "— must reference an existing object id"
                        )
                    elif ref not in defined and ref != "all":
                        issues.append(
                            f"beat {bi + 1} action {ai + 1}: {op} target = "
                            f"'{ref}' but no object with that id has been defined yet"
                        )
                # track ids defined by transform (it changes an existing object)
                if op == "transform" and action.id:
                    defined.add(action.id)
        return issues

    def dump_clean_json(self, indent: int | None = None) -> str:
        """Dump spec as JSON with null fields stripped for readability."""
        import json

        def _strip_nulls(obj):
            if isinstance(obj, dict):
                return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
            if isinstance(obj, list):
                return [_strip_nulls(item) for item in obj]
            return obj

        raw = self.model_dump()
        cleaned = _strip_nulls(raw)
        return json.dumps(cleaned, indent=indent)
