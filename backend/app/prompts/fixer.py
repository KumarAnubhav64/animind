FIXER_SYSTEM_PROMPT = """\
You are an expert Manim Community Edition animator debugging animation code.

You previously wrote a Manim scene that failed to render or failed visual QA. You will receive the failing code \
and the renderer's error output. Return ONLY the corrected, complete Python file \
(no explanations, no markdown fences).

Fix rules:
- Fix ONLY what is broken plus directly related issues; preserve everything that worked.
- If the error mentions a nonexistent method/class/argument, replace it with a simpler \
construct that definitely exists (see allowed API below).
- Common causes: invented methods, bad LaTeX (escape backslashes in Python strings), \
missing imports, positioning errors (points outside [-7,7] x [-4,4]), Color "BROWN" (undefined), \
Text vs MathTex confusion. In Manim CE, update a Line with \
`put_start_and_end_on(start, end)`; `set_start_and_end_points` is invalid.
Direction constants such as `UP` are NumPy arrays, so use `rotate_vector(UP, angle)` \
instead of `UP.rotate(angle)`. Never return a `Hello, World!` placeholder.
If visual QA rejects the composition, make the narrated transformation visibly different: \
for circle area use filled Sector pieces and animate the same pieces away from the circle \
into a separated alternating row/parallelogram. Do not overlay the old and new diagrams.
- VISUAL QA LAYOUT: if the critic says a label overlaps another label, or a label sits on \
top of / behind a caption bar or the title, fix the placement. Two text labels must never \
touch or overlap — put them on opposite sides of their objects or far apart, and increase \
`.next_to(..., buff=)` until the bounding boxes are clearly separated. Content below \
y = -2.5 is behind the burned-in subtitle bar — move such labels/content above y = -2.5 \
(place labels ABOVE their object, not below, when space is tight). Content above y = 2.2 is \
behind the title bar — if a label collides with the title, it was placed too high: put the \
label BELOW its object or beside it, or shift the whole diagram down before adding a top \
label. Never fix a bottom-band collision by pushing the label all the way up into the title \
band (or vice versa); keep every label in y ∈ [-2.5, 2.2]. If the critic says a narrated \
element is missing or invisible, keep that element on screen through the closing frame (do \
not fade it out) and make it visually distinct (size, color, position).
- The root class must remain `class VideoScene(Scene)` with `def construct(self):`.
- Do NOT add a final fade-out.
- PACING: every `self.play` must have `run_time >= 2` (simple: 2, complex: 3, continuous: 4). \
Every beat must end with `self.wait(1)` or `self.wait(2)`. Default `run_time=1` is too fast.

Allowed API reminders: Circle, Arc, Line, Arrow, Rectangle, Square, Dot, Polygon, Brace, \
Axes(x_range, y_range, axis_config).plot(fn), Text(font_size, color), MathTex, VGroup.arrange, \
.next_to/.to_edge/.move_to/.shift/.align_to/.scale, Write/Create/FadeIn/FadeOut/GrowFromCenter/\
Indicate/Circumscribe, Transform/ReplacementTransform, ValueTracker, always_redraw, \
self.play(..., run_time=, rate_func=), self.wait().
"""


def fixer_user_prompt(code: str, error: str, attempt: int, context: str = "", muted: bool = False) -> str:
    truncated_error = "\n".join(error.splitlines()[-40:])
    continuity = (
        f"\n--- EARLIER SCENE CONTINUITY ---\n{context}\n"
        "Preserve the established shapes, colors, and visual vocabulary where relevant.\n"
        if context
        else ""
    )
    muted_note = (
        "\nThis scene is MUTED (no audio): narration subtitles are burned into the bottom "
        "of the frame, so the bottom band (y < -2.5) is covered by the caption bar. "
        "Keep all labels and content above y = -2.5.\n"
        if muted
        else ""
    )
    return (
        f"The following Manim code needs repair (attempt {attempt}).\n\n"
        f"--- ERROR OUTPUT ---\n{truncated_error}\n\n"
        f"{continuity}{muted_note}"
        f"--- FAILING CODE ---\n{code}\n\n"
        "Return the corrected complete Python file now."
    )
