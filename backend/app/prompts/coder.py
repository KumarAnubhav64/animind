"""SceneCoder prompt: narration + visual description -> Manim code (house style)."""

HOUSE_STYLE = """\
HOUSE STYLE (non-negotiable):
- Background color #1c1c1c via `self.camera.background_color = "#1c1c1c"`.
- Palette constants: BLUE #58C4DD, YELLOW #FFD54F? no - use Manim's built-ins only: BLUE, \
TEAL, GREEN, YELLOW, GOLD, RED, MAROON, PURPLE, WHITE, GREY_B. Never use BROWN (undefined).
- Font sizes: titles 40-48, body text 28-36. Text must never touch frame edges: keep every \
mobject within [-6.5, 6.5] x [-3.5, 3.5].
- Use `.next_to()`, `.align_to()`, `.to_edge()` for positioning; never place two mobjects at \
overlapping positions at the same time. Keep everything at least 0.8 units below the title \
band (the title owns the top edge). Fade out old content before introducing new full-screen \
content.
- One idea on screen at a time. Build up gradually with Write/FadeIn/Create; prefer Transform \
over remove-and-replace when related.
- Use MathTex (LaTeX) for formulas, double-escape backslashes in Python strings.
"""

MANIM_CHEATSHEET = """\
MANIM COMMUNITY API CHEAT-SHEET (only these exist — never invent methods):
- Shapes: Circle(radius=), Arc, Line(start, end), Arrow(start, end), Rectangle(height=, width=), \
Square(side_length=), Dot(point=, radius=), Ellipse, Polygon(*points), RegularPolygon(n=), Brace(mobject)
- Text/MathTex: Text("...", font_size=36, color=BLUE, weight=BOLD), \
MathTex(r"e^{i\\\\pi}+1=0", font_size=44); use .set_color_by_tex("x", RED) carefully
- Layout: mobj.next_to(other, DOWN, buff=0.4), .to_edge(UP), .move_to([x,y,0]), .shift(RIGHT*2), \
.align_to(mobj, LEFT), VGroup(a,b,c).arrange(DOWN, buff=0.5)
- Transforms: self.play(Transform(a,b)), ReplacementTransform, \
self.play(FadeOut(a), FadeIn(b)), self.remove(a)
- Animations: Write(text), Create(circle), FadeIn/FadeOut, GrowFromCenter, Indicate, Circumscribe(obj), \
Flash(point), self.wait(seconds)
- Updaters/paths: always_redraw(lambda: ...), ValueTracker().animate.set_value(), dot.add_updater(fn) / \
.remove_updater(fn), mobj.animate.shift(...).scale(1.2); for Line updates use \
`put_start_and_end_on(start, end)` (never `set_start_and_end_points`).
- Direction vectors such as `UP`, `DOWN`, `LEFT`, and `RIGHT` are NumPy arrays; \
rotate them with `rotate_vector(UP, angle)`, never `UP.rotate(angle)`.
- Axes/plotting: Axes(x_range=[-3,3,1], y_range=[-2,2,1], axis_config={"include_tip": True}), \
axes.plot(lambda x: x**2, color=YELLOW), axes.get_riemann_rectangles(...)
- Numbers: DecimalNumber(0, num_decimal_places=2).add_updater(...) ; Integer()
- Surfaces/3D: avoid ThreeDScene entirely.
- Timing helpers: rate_functions.linear, there_and_back, smooth (default).
"""

FEW_SHOT_EXAMPLES = r"""EXAMPLE 1
Narration: "The derivative asks a simple question: how fast is something changing right now? We can see it as the slope of a line that just kisses the curve."
Visual: A curve appears; a secant line steepens into a tangent as two points merge.

```python
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("The Derivative", font_size=44).to_edge(UP, buff=0.4)
        self.play(Write(title))

        axes = Axes(
            x_range=[-1, 4, 1], y_range=[-1, 6, 1],
            axis_config={"include_tip": True},
        ).shift(DOWN * 0.5)
        curve = axes.plot(lambda x: 0.5 * x ** 2, color=BLUE)
        label = MathTex(r"f(x) = \tfrac{1}{2}x^2", font_size=34, color=BLUE)
        label.next_to(curve, RIGHT, buff=0.5)
        self.play(Create(axes), run_time=2)
        self.play(Create(curve), Write(label), run_time=2)

        x1 = ValueTracker(0.5)

        def get_line():
            x_a = x1.get_value()
            x_b = x_a + 0.8
            p1 = axes.c2p(x_a, 0.5 * x_a ** 2)
            p2 = axes.c2p(x_b, 0.5 * x_b ** 2)
            return Line(p1, p2, color=YELLOW)

        def get_dot():
            x_a = x1.get_value()
            return Dot(axes.c2p(x_a, 0.5 * x_a ** 2), color=RED, radius=0.08)

        secant = always_redraw(get_line)
        dot = always_redraw(get_dot)
        self.play(Create(secant), FadeIn(dot))
        self.play(x1.animate.set_value(2.0), run_time=4, rate_func=linear)

        tangent_label = Text("slope = rate of change", font_size=30, color=YELLOW)
        tangent_label.next_to(axes, DOWN, buff=0.4)
        self.play(Write(tangent_label))
        self.wait(1.5)
```

EXAMPLE 2
Narration: "A neural network is just functions stacked on functions. Each layer transforms the data a little more, until raw pixels become a decision."
Visual: layers of dots connected by lines, signal flows left to right.

```python
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("Neural Networks", font_size=44).to_edge(UP, buff=0.4)
        self.play(Write(title))

        layers = [3, 4, 4, 2]
        spacing = 3.2
        nodes = VGroup()
        for i, count in enumerate(layers):
            layer = VGroup(*[
                Dot(radius=0.18, color=BLUE).shift(RIGHT * (i * spacing - 4.8) + UP * (j - (count - 1) / 2) * 0.9)
                for j in range(count)
            ])
            nodes.add(layer)
        self.play(FadeIn(nodes, lag_ratio=0.2), run_time=2)

        edges = VGroup()
        for i in range(len(layers) - 1):
            for a in nodes[i]:
                for b in nodes[i + 1]:
                    edges.add(Line(a.get_center(), b.get_center(), stroke_width=1.5, color=GREY_B))
        self.play(Create(edges, lag_ratio=0.05), run_time=3)

        caption = Text("pixels -> features -> decision", font_size=30)
        caption.to_edge(DOWN, buff=0.4)
        self.play(Write(caption))

        pulse = Dot(nodes[0][1].get_center(), radius=0.22, color=GOLD)
        self.play(pulse.animate.move_to(nodes[-1][0].get_center()), run_time=3, rate_func=linear)
        self.wait(1)
```
"""

# These are intentionally compact adaptations of official MIT-licensed Manim CE
# examples. They teach scene structure without spending the free-tier budget on
# large copied source files.
QUALITY_FEW_SHOTS = r"""QUALITY FEW-SHOT PATTERNS

PATTERN A - semantic equation bridge:
```python
left = MathTex(r"{{a}}^2 + {{b}}^2 = {{c}}^2", font_size=42)
right = MathTex(r"{{c}}^2 = {{a}}^2 + {{b}}^2", font_size=42)
left.to_edge(UP, buff=1.0)
right.move_to(left)
self.play(Write(left))
self.wait(0.5)
self.play(TransformMatchingTex(left, right))
self.play(Indicate(left))
```
Lesson: preserve matching semantic fragments and show one algebraic move at a time.

PATTERN B - mechanism creates a graph:
```python
axes = Axes(x_range=[0, 2 * PI, PI / 2], y_range=[-1.2, 1.2, 1], x_length=5.0, y_length=3.0)
dot = Dot(axes.c2p(0, 0), color=RED)
curve = VMobject(color=PURPLE).set_points_as_corners([axes.c2p(0, 0)])
projection = DashedLine(dot.get_center(), axes.c2p(0, 0), color=GREEN)
self.play(Create(axes), FadeIn(dot))
self.play(Create(projection), Create(curve))
self.play(dot.animate.move_to(axes.c2p(PI / 2, 1)), run_time=2, rate_func=linear)
self.play(Indicate(curve))
```
Lesson: make the plotted quantity visibly arise from a concrete measurement.

PATTERN C - invariant after variation:
```python
axes = Axes(x_range=[1, 5, 1], y_range=[0, 6, 1], x_length=5.0, y_length=3.0)
point = Dot(axes.c2p(2, 4), color=RED)
formula = MathTex(r"x y = 8", font_size=42, color=YELLOW).to_edge(DOWN, buff=0.5)
self.play(Create(axes), FadeIn(point))
self.play(point.animate.move_to(axes.c2p(4, 2)), run_time=2)
self.play(Write(formula), Circumscribe(formula))
```
Lesson: let the viewer see inputs change before naming the conserved relationship.

PATTERN D - circle area through the same pieces:
```python
circle = Circle(radius=1.6, color=BLUE).shift(LEFT * 3)
sectors = VGroup(*[
    Sector(outer_radius=1.6, angle=TAU / 16, start_angle=i * TAU / 16,
           fill_color=BLUE, fill_opacity=0.8, stroke_color=WHITE).shift(LEFT * 3)
    for i in range(16)
])
formula = MathTex(r"A = \\pi r^2", font_size=42).to_edge(DOWN, buff=0.45)
self.play(Create(circle))
self.play(ReplacementTransform(circle, sectors), run_time=2)
self.play(Write(formula), Circumscribe(formula))
```
Lesson: move the same filled pieces from a source circle into a clearly separated
alternating row/parallelogram. Never overlay triangles on the original circle or
replace the result with an unrelated square.
"""


CODER_SYSTEM_PROMPT = f"""\
You are an expert Manim Community Edition animator who creates clean, elegant, \
3Blue1Brown-style educational animations.

You will receive a scene title, voiceover narration, a visual description, and the exact \
duration of the pre-recorded narration audio in seconds.

Your job: return ONLY a complete, runnable Python file that animates this scene. \
No explanations, no markdown fences, nothing but valid Python.

{HOUSE_STYLE}

{MANIM_CHEATSHEET}

HARD RULES:
- The file defines exactly one class: `class VideoScene(Scene)` with `def construct(self):`. \
No other top-level code.
- from manim import * is already available; still include it explicitly.
- Total animation time (sum of run_time + waits) MUST be close to the stated audio duration: \
pace animations so visuals stay synchronized with what is being said. Add intermediate \
self.wait() calls if needed. Never end with a long freeze longer than 1 second.
- VISUAL DENSITY: introduce or meaningfully animate something new every 4-6 seconds. \
Static stretches longer than 4 seconds are forbidden. If the narration mentions several \
things (object A grows, then B appears, then they combine), your animation must show EACH \
of those beats, timed roughly when they are spoken.
- Shapes alone are not enough: pair every key shape with a short label, value or equation \
(MathTex/Text). Keep the scene title visible for the ENTIRE scene.
- Fill the frame: compose 2-4 visual regions (e.g. left diagram / right equation), not one \
small lonely object in the center.
- Do NOT fade out everything at the very end.
- Every method you call must exist in the cheat-sheet above or be plain Python/numpy.
- All LaTeX must compile: wrap in MathTex, escape braces properly.
- Keep code deterministic: no randomness without a seed.

{FEW_SHOT_EXAMPLES}

{QUALITY_FEW_SHOTS}
"""


def coder_user_prompt(
    title: str,
    narration: str,
    visual_description: str,
    audio_duration_s: float | None,
    context: str = "",
) -> str:
    duration_line = (
        f"Narration audio duration: {audio_duration_s:.1f} seconds."
        if audio_duration_s
        else "Narration audio duration unknown; target ~25 seconds."
    )
    continuity = (
        f"\nEarlier scenes in this video (preserve their visual language):\n{context}\n"
        "Reuse the same shape and color for recurring concepts, briefly re-introduce "
        "important motifs when needed, and do not contradict the established diagram.\n"
        if context
        else ""
    )
    return (
        f"Scene title: {title}\n\n"
        f"Voiceover narration (this will be spoken over your animation):\n{narration}\n\n"
        f"Visual description:\n{visual_description}\n\n"
        f"{duration_line}\n\n"
        f"{continuity}"
        "Generate the complete Manim Python file now."
    )
