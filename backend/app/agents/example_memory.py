"""Dynamic few-shot memory: distilled Manim CE examples retrieved just-in-time
for the raw codegen and Fixer prompts.

Why: static few-shot sections live at the END of the system prompt and are the
FIRST thing `_fit_to_budget` drops under Groq's 8k per-request cap. Instead of
gambling that the one-size-fits-all example survives, we keep a small corpus of
house-style pattern cards offline and append the best match for the CURRENT
scene to the tail of the human turn — where `_fit_to_budget`'s Level-3
middle-cut preserves the head and tail, so the example is the LAST thing cut.

Each card is a hand-distilled adaptation of an MIT-licensed official gallery
scene (source tracked in research/MANIM_FEW_SHOTS.md), normalized to AniMind's
house style: `class VideoScene(Scene)`, explicit run_time, no legacy APIs
(ShowCreation, TexText, Axes.get_graph), dark background.

Usage:
    block = lookup_example("a dot slides along a parabola to its minimum")
    # -> str | None  (None when nothing scores — never invents)
"""

import re

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExampleCard:
    slug: str
    heading: str
    keywords: tuple[str, ...] = field(default_factory=tuple)
    apis: tuple[str, ...] = field(default_factory=tuple)
    lesson: str = ""
    code: str = ""

    def render(self) -> str:
        lesson = f"Lesson: {self.lesson}" if self.lesson else ""
        return "\n".join(
            part for part in (
                f"# {self.heading}",
                lesson,
                "Adapt the TECHNIQUE, not the numbers — match this scene's colors/labels",
                "and your narration duration. This example uses the SAME Manim API you must use.",
                "```python",
                self.code.strip(),
                "```",
            ) if part
        )


# House-style distilled adaptations of the MIT-licensed official gallery
# (ManimCommunity/manim v0.21.0 docs/source/examples.rst). Keep each card's
# code COMPACT (~30-70 lines) so injecting one card stays cheap.
CARDS: tuple[ExampleCard, ...] = (
    ExampleCard(
        slug="sine-unit-circle",
        heading="Orbiting dot draws a sine wave (always_redraw trace)",
        keywords=(
            "sine", "circle", "orbit", "unit circle", "trig",
            "trace", "wave", "sinusoid", "oscillat", "harmonic",
        ),
        apis=("ValueTracker", "always_redraw", "DashedLine", "Axes.plot"),
        lesson=(
            "Drive every moving part from ONE ValueTracker via always_redraw lambdas so the "
            "rotating radius, its vertical projection, and the growing trace stay in sync."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("Sine from a Circle", font_size=40).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        center = np.array([-4.2, -0.4, 0])
        R = 1.7
        circle = Circle(radius=R, color=BLUE).move_to(center)
        axes = Axes(
            x_range=[0, 8, 1], y_range=[-2, 2, 1],
            x_length=6.0, y_length=3.2,
        ).shift(RIGHT * 2.6 + DOWN * 0.4)
        axes_labels = axes.get_axis_labels(x_label="x", y_label="sin x")

        angle = ValueTracker(0.0)

        def dot_pos():
            a = angle.get_value()
            return center + R * np.array([np.cos(a), np.sin(a), 0])

        orbiting_dot = always_redraw(lambda: Dot(dot_pos(), color=RED, radius=0.08))
        radius_line = always_redraw(lambda: Line(center, dot_pos(), color=YELLOW))
        projection = always_redraw(
            lambda: DashedLine(
                dot_pos(),
                axes.c2p(angle.get_value(), np.sin(angle.get_value())),
                color=GREEN,
            )
        )
        curve_dot = always_redraw(
            lambda: Dot(axes.c2p(angle.get_value(), np.sin(angle.get_value())), color=GOLD, radius=0.08)
        )
        trace = always_redraw(
            lambda: axes.plot(
                lambda x: np.sin(x), color=GOLD,
                x_range=[0, min(angle.get_value(), 8)],
            )
        )

        self.play(Create(circle), run_time=2)
        self.play(Create(axes), Write(axes_labels), run_time=2)
        self.add(orbiting_dot, radius_line, projection, curve_dot, trace)
        self.play(angle.animate.set_value(TAU), run_time=6, rate_func=linear)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="sliding-dot-argmin",
        heading="Sliding dot searches a graph for its minimum (ValueTracker + updater)",
        keywords=(
            "minimum", "maximum", "argmin", "optimiz", "search",
            "sliding", "tracking", "gradient descent", "2 * (x",
            "parabola", "function value", "dot along the graph",
        ),
        apis=("ValueTracker", "Mobject.add_updater", "Axes.plot", "Axes.c2p"),
        lesson=(
            "Plot the curve once, then move a dot along it with a ValueTracker updater "
            "(x = t, y = f(x)) — the graph is fixed, only the dot travels."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("Searching for the Minimum", font_size=38).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        axes = Axes(
            x_range=[0, 10, 1], y_range=[0, 60, 10],
            x_length=8.5, y_length=4.0,
        ).shift(DOWN * 0.3)
        labels = axes.get_axis_labels(x_label="x", y_label="f(x)")

        def func(x):
            return 2 * (x - 5) ** 2

        graph = axes.plot(func, color=MAROON)
        t = ValueTracker(0.0)
        dot = Dot(axes.c2p(0, func(0)), color=YELLOW, radius=0.09)
        dot.add_updater(
            lambda d: d.move_to(axes.c2p(t.get_value(), func(t.get_value())))
        )

        xs = np.linspace(*axes.x_range[:2], 400)
        argmin = float(xs[func(xs).argmin()])
        spot = Dot(axes.c2p(argmin, func(argmin)), color=RED, radius=0.09)

        self.play(Create(axes), Write(labels), run_time=2)
        self.play(Create(graph), run_time=2)
        self.add(dot)
        self.play(t.animate.set_value(9), run_time=3)
        self.play(t.animate.set_value(argmin), run_time=3)
        self.play(Indicate(spot), run_time=2)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="invariant-rectangle",
        heading="Moving rectangle keeps a hidden invariant (always_redraw polygon)",
        keywords=(
            "invariant", "conserved", "constant area", "rectangle", "inverse",
            "k / x", "k over x", "reciprocal", "area stays", "fixed product",
            "x*y", "x times y", "hyperbola",
        ),
        apis=("always_redraw", "Polygon", "ValueTracker", "Axes.c2p"),
        lesson=(
            "Recompute the whole polygon every frame from one ValueTracker; its area "
            "(x * k/x) never changes — reveal the invariant by letting x slide, then "
            "label the constant area."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("A Hidden Invariant", font_size=40).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        ax = Axes(
            x_range=[0, 10, 1], y_range=[0, 10, 1],
            x_length=7.0, y_length=4.6,
        ).shift(DOWN * 0.2)
        k = 10.0
        graph = ax.plot(lambda x: k / x, color=YELLOW, x_range=[k / 10, 10, 0.01])
        t = ValueTracker(2.0)

        def rectangle():
            x = t.get_value()
            return Polygon(
                ax.c2p(0, 0), ax.c2p(x, 0),
                ax.c2p(x, k / x), ax.c2p(0, k / x),
                fill_color=BLUE, fill_opacity=0.5, stroke_color=WHITE, stroke_width=2,
            )

        box = always_redraw(rectangle)
        corner_dot = always_redraw(
            lambda: Dot(ax.c2p(t.get_value(), k / t.get_value()), color=RED, radius=0.08)
        )
        area_label = always_redraw(
            lambda: MathTex(f"A = {k:.0f}").scale(0.9)
            .move_to(ax.c2p(t.get_value() / 2, k / (2 * t.get_value())))
        )

        self.play(Create(ax), run_time=2)
        self.play(Create(graph), run_time=2)
        self.add(box, corner_dot, area_label)
        self.play(t.animate.set_value(7), run_time=3)
        self.play(t.animate.set_value(2), run_time=3)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="area-under-curve",
        heading="Riemann rectangles then the filled area under a curve",
        keywords=(
            "area under", "integral", "riemann", "rectangles", "shade",
            "fill under", "definite integral", "approximating area",
        ),
        apis=("Axes.plot", "Axes.get_riemann_rectangles", "Axes.get_area"),
        lesson=(
            "plot() the curve once and pass the PLOTTED mobject to "
            "get_riemann_rectangles / get_area — never a bare lambda. Fade the bars "
            "before fading in the filled area so the frame never stacks both."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("Approximating Area", font_size=40).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        ax = Axes(
            x_range=[0, 5, 1], y_range=[0, 6, 1],
            x_length=7.5, y_length=4.2,
        ).shift(DOWN * 0.3)
        labels = ax.get_axis_labels(x_label="x", y_label="f(x)")
        curve = ax.plot(lambda x: 4 * x - x ** 2, x_range=[0, 4], color=BLUE)
        riemann = ax.get_riemann_rectangles(
            curve, x_range=[0.5, 3.5], dx=0.2,
            color=TEAL, fill_opacity=0.6,
        )
        area = ax.get_area(curve, x_range=[0.5, 3.5], color=GREEN, opacity=0.4)

        self.play(Create(ax), Write(labels), run_time=2)
        self.play(Create(curve), run_time=2)
        self.play(FadeIn(riemann), run_time=2)
        self.wait(1)
        self.play(FadeOut(riemann), run_time=1)
        self.play(FadeIn(area, shift=UP * 0.2), run_time=2)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="equation-bridge",
        heading="Morph one formula into another (TransformMatchingTex)",
        keywords=(
            "equation", "formula", "algebra", "morph", "transform the equation",
            "derive", "algebraic", "factor", "expand", "(a", "identity",
            "show the steps", "tex", "math tex",
        ),
        apis=("TransformMatchingTex", "MathTex", "SurroundingRectangle", "Indicate"),
        lesson=(
            "Keep both sides on the same spot; TransformMatchingTex reuses the matched "
            "TeX terms so the viewer sees WHICH pieces moved, then box/indicate the key term."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("One Algebraic Move", font_size=40).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        left = MathTex("(a+b)^2").scale(1.7)
        right = MathTex("a^2", "+", "2ab", "+", "b^2").scale(1.7)
        left.move_to(ORIGIN)
        right.move_to(ORIGIN)

        self.play(Write(left), run_time=2)
        self.play(left.animate.shift(LEFT * 3), run_time=2)
        self.wait(1)
        self.play(TransformMatchingTex(left, right), run_time=3)
        self.wait(1)
        box = SurroundingRectangle(right[2], color=YELLOW, buff=0.12)
        self.play(Create(box), run_time=1)
        self.play(Indicate(right[2], color=RED), run_time=2)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="rotating-angle",
        heading="Live angle readout between two lines (Angle + ValueTracker)",
        keywords=(
            "angle", "theta", "rotation angle", "degrees", "radian",
            "between two lines", "growing angle", "swinging line",
        ),
        apis=("Angle", "ValueTracker", "Line.become", "always_redraw"),
        lesson=(
            "Rotate one line about a fixed pivot from a ValueTracker (recreate it with "
            ".become(...).rotate(...)), then always_redraw the Angle arc and its theta label."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("The Angle Between Them", font_size=38).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        pivot = np.array([-2.5, -0.6, 0])
        arm = pivot + RIGHT * 5
        base_line = Line(pivot, arm, color=WHITE)
        theta = ValueTracker(35.0)

        def rotated_line():
            return Line(pivot, arm, color=YELLOW).rotate(
                theta.get_value() * DEGREES, about_point=pivot
            )

        moving_line = rotated_line()  # already rotated so Angle never sees a colinear pair
        moving_line.add_updater(lambda ln: ln.become(rotated_line()))
        angle_arc = always_redraw(
            lambda: Angle(base_line, moving_line, radius=0.8, color=GREEN)
        )
        angle_label = always_redraw(
            lambda: MathTex(r"\theta", color=GREEN).move_to(
                Angle(base_line, moving_line, radius=1.3).point_from_proportion(0.5)
            )
        )

        self.play(Create(base_line), run_time=2)
        self.add(moving_line, angle_arc, angle_label)
        self.wait(1)
        self.play(theta.animate.set_value(160), run_time=3)
        self.play(theta.animate.set_value(35), run_time=3)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="follow-camera",
        heading="Camera pans to follow the action (MovingCameraScene)",
        keywords=(
            "zoom", "camera", "pan", "close up", "follow",
            "focus on", "frame", "closeup", "pull back",
        ),
        apis=("self.camera.frame", "MovingCameraScene", "Mobject.add_updater"),
        lesson=(
            "Write `self.camera.frame.animate.scale(...).move_to(...)` on a plain "
            "VideoScene — the pipeline auto-upgrades it to MovingCameraScene. Follow "
            "only the X of a moving dot so the title band stays on screen."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("Camera Follows the Dot", font_size=36).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        axes = Axes(
            x_range=[-1, 11, 1], y_range=[-1.5, 1.5, 1],
            x_length=12.0, y_length=4.0,
        ).shift(DOWN * 0.4)
        graph = axes.plot(lambda x: np.sin(x), color=BLUE, x_range=[0, 10])
        moving_dot = Dot(axes.c2p(0, np.sin(0)), color=ORANGE, radius=0.1)

        self.play(Create(axes), run_time=2)
        self.play(Create(graph), run_time=2)
        self.add(moving_dot)
        self.play(
            self.camera.frame.animate.scale(0.6).move_to(moving_dot),
            run_time=2,
        )

        def follow_x(mob):
            mob.move_to([moving_dot.get_x(), 0.0, 0])

        self.camera.frame.add_updater(follow_x)
        self.play(
            moving_dot.animate.move_to(axes.c2p(9, np.sin(9))),
            run_time=5, rate_func=linear,
        )
        self.camera.frame.remove_updater(follow_x)
        self.play(self.camera.frame.animate.scale(1.0 / 0.6), run_time=2)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="point-moves-path",
        heading="Compose motion: a dot rides a closed loop, then changes shape",
        keywords=(
            "orbit", "path", "ride", "around the circle", "move along",
            "loop", "spin a dot", "circular path", "trajectory",
        ),
        apis=("MoveAlongPath", "Transform", "GrowFromCenter"),
        lesson=(
            "Place the dot on the path's start point before MoveAlongPath; chain "
            "MoveAlongPath (spatial ride) and Transform (identity change) for a story beat."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("Along the Path", font_size=40).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        circle = Circle(radius=2.3, color=BLUE).shift(DOWN * 0.3)
        dot = Dot(circle.get_right(), color=RED, radius=0.09)
        square = Square(side_length=0.45, color=GOLD).move_to(circle.get_left())

        self.play(Create(circle), run_time=2)
        self.play(GrowFromCenter(square), run_time=2)
        self.add(dot)
        self.play(MoveAlongPath(dot, circle), run_time=4, rate_func=linear)
        self.wait(1)
        self.play(Transform(dot, square), run_time=2)
        self.wait(1)
''',
    ),
    ExampleCard(
        slug="flow-diagram-nodes",
        heading="Process flow: labeled boxes chained by arrows, one signal travels the path",
        keywords=(
            "flow chart", "flowchart", "flow diagram", "process diagram",
            "workflow diagram", "sequence of events", "chain of events",
            "workflow", "pipeline", "cascade", "trigger", "triggers", "triggered",
            "email", "emails", "sign up", "sign-up", "signup", "subscribe",
            "subscription", "newsletter", "mailing list", "arrow", "arrows",
            "clipping", "cut off", "frame edge", "off-screen", "out of frame",
        ),
        apis=("RoundedRectangle", "Arrow", "MoveAlongPath", "scale_to_fit_width", "VGroup"),
        lesson=(
            "Build each node as a VGroup(RoundedRectangle + Text) and SCALE the label to fit "
            "INSIDE its box with scale_to_fit_width, then keep every node well inside the "
            "frame (|x| <= 6.1). Connect the boxes edge-to-edge with Arrow(node1.get_right(), "
            "node2.get_left(), buff=0.25) — never leave nodes unconnected. Reveal nodes "
            "first, then edges, then send a Dot down each arrow with MoveAlongPath so the "
            "trigger visibly launches the chain."
        ),
        code=r'''
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("A Request Flows Through", font_size=38).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=2)

        def node(width, height, label, color):
            shape = RoundedRectangle(
                width=width, height=height, corner_radius=0.18,
                fill_color=color, fill_opacity=0.35,
                stroke_color=color, stroke_width=3,
            )
            text = Text(label, font_size=28).scale_to_fit_width(width * 0.78)
            return VGroup(shape, text)

        n1 = node(2.9, 0.85, "User submits form", BLUE).move_to([-4.6, 0.4, 0])
        n2 = node(2.9, 0.85, "Server validates input", TEAL).move_to([0.0, 0.4, 0])
        n3 = node(2.9, 0.85, "Stores in database", PURPLE).move_to([4.6, 0.4, 0])

        a1 = Arrow(n1.get_right(), n2.get_left(), buff=0.25, color=YELLOW, stroke_width=6)
        a2 = Arrow(n2.get_right(), n3.get_left(), buff=0.25, color=YELLOW, stroke_width=6)

        self.play(GrowFromCenter(n1), run_time=2)
        self.play(GrowFromCenter(n2), run_time=2)
        self.play(GrowFromCenter(n3), run_time=2)
        self.play(Create(a1), Create(a2), run_time=2)

        dot = Dot(n1.get_right(), color=RED, radius=0.08)
        self.add(dot)
        self.play(MoveAlongPath(dot, a1), run_time=2)
        self.play(Indicate(n2, color=YELLOW), run_time=1)
        self.play(MoveAlongPath(dot, a2), run_time=2)
        self.play(Indicate(n3, color=YELLOW), run_time=1)
        self.wait(1)
''',
    ),
)

_CARD_INDEX = {card.slug: card for card in CARDS}

_WORD_RE = re.compile(r"[a-z0-9']+")
_PHRASE_WEIGHT = 3
_SLUG_HEADING_BONUS = 5


def _score(card: ExampleCard, text_lower: str, tokens: set[str]) -> int:
    score = 0
    for kw in card.keywords:
        if " " in kw:
            if kw in text_lower:
                score += _PHRASE_WEIGHT
        elif kw in tokens:
            score += 1
    for api in card.apis:
        if api.lower() in text_lower:
            score += 2
    if card.slug.replace("-", " ") in text_lower or card.heading.lower() in text_lower:
        score += _SLUG_HEADING_BONUS
    return score


def lookup_example(*texts: str, max_entries: int = 1) -> str | None:
    """Return a compact house-style example card block for the best-matching
    cards, or None. Matches on the union of the provided texts (title +
    narration + visual description, and for the Fixer the renderer error too).
    Returns nothing when no card scores — never invents an example."""
    text_lower = " ".join(t for t in texts if t).lower()
    if not text_lower.strip():
        return None
    tokens = set(_WORD_RE.findall(text_lower))
    scored = sorted(
        ((score, card) for card in CARDS if (score := _score(card, text_lower, tokens)) > 0),
        key=lambda pair: -pair[0],
    )
    if not scored:
        return None
    picked = [card for _, card in scored[:max_entries]]
    header = (
        "REFERENCE EXAMPLE (MIT-licensed official Manim gallery, distilled to house style): "
        "study this technique for YOUR scene. Do NOT return this code verbatim."
    )
    return header + "\n\n" + "\n\n".join(card.render() for card in picked)


def get_card(slug: str) -> ExampleCard | None:
    return _CARD_INDEX.get(slug)
