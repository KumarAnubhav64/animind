# AniMind Few-Shot References

Curated on 2026-08-27 for Manim Community Edition 0.21.0. The code patterns below
are reviewed adaptations, not verbatim copies. Source links and licenses are kept
separate so prompt examples do not blur provenance.

## Example Memory Cards (`backend/app/agents/example_memory.py`)

House-style distilled cards injected at runtime into the raw codegen / Fixer prompts
(see `_append_example_memory` in `backend/app/agents/scene_graph.py`). Provenance of
each `slug` below. Slugs 1-4 reuse the gallery scenes tracked in the older table;
5-9 extend the corpus (9 distills the directed-process technique from `MovingDiGraph`,
tracked in the Primary Sources table below).

| Card slug | Distilled from (source scene) | Source | License | House-style adaptation |
|---|---|---|---|---|
| `sine-unit-circle` | [`SineCurveUnitCircle`](https://docs.manim.community/en/stable/examples.html#sinecurveunitcircle) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | One ValueTracker drives the orbiting dot, its projection, and the growing trace via `always_redraw`; vertical content kept within y ∈ [-2.5, 2.2] |
| `sliding-dot-argmin` | [`ArgMinExample`](https://docs.manim.community/en/stable/examples.html#argminexample) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Graph plotted once; ValueTracker + `add_updater` slides a dot along f(x); deterministic min flagged with `Indicate` |
| `invariant-rectangle` | [`PolygonOnAxes`](https://docs.manim.community/en/stable/examples.html#polygononaxes) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | `always_redraw` Polygon from one tracker; corner dot + area label float on top |
| `area-under-curve` | [`GraphAreaPlot`](https://docs.manim.community/en/stable/examples.html#graphareaplot) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | `get_riemann_rectangles` / `get_area` fed the PLOTTED curve mobject (never a bare lambda); bars fade out before the filled area fades in |
| `equation-bridge` | [`MovingFrameBox` / `TransformMatchingTex` gallery scenes](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Both formulas on the same spot; `TransformMatchingTex` shows which TeX pieces moved; key term boxed + indicated |
| `rotating-angle` | [`MovingAngle`](https://docs.manim.community/en/stable/examples.html#movingangle) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Rotating line rebuilt with `.become(...).rotate(...)` from a ValueTracker; `Angle` arc + `\theta` label via `always_redraw` |
| `follow-camera` | [`FollowingGraphCamera`](https://docs.manim.community/en/stable/examples.html#followinggraphcamera) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Written on plain `VideoScene(Scene)` — the pipeline auto-upgrades to MovingCameraScene; camera follows only the dot's X so the title band stays framed |
| `point-moves-path` | [`PointMovingOnShapes`](https://docs.manim.community/en/stable/examples.html#pointmovingonshapes) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Dot pre-placed on the path's start before `MoveAlongPath`; motion then `Transform` into another shape for a story beat |
| `flow-diagram-nodes` | [`MovingDiGraph`](https://docs.manim.community/en/stable/reference/manim.mobject.graph.DiGraph.html#movingdigraph) in the [MIT-licensed source](https://github.com/ManimCommunity/manim/blob/v0.21.0/manim/mobject/graph.py) | MIT | Labels `scale_to_fit_width` INSIDE rounded-rect nodes; nodes chained edge-to-edge with `Arrow(node.get_right(), node.get_left(), buff=...)`; revealed nodes → edges → a `Dot` sent via `MoveAlongPath` so flow reads causally |

> The example card blocks contain a `from manim import *` header only so they are
> runnable if copied; the header's `#` comment text is the docs' prose, not video
> content.

## Primary Sources

| Pattern | Source | License | Use in AniMind |
|---|---|---|---|
| Semantic equation transformation | [TransformMatchingTex docs](https://docs.manim.community/en/stable/reference/manim.animation.transform_matching_parts.TransformMatchingTex.html) and the [official source](https://github.com/ManimCommunity/manim/blob/v0.21.0/manim/animation/transform_matching_parts.py) | MIT | Preserve identity of terms while formalizing an idea |
| Moving point on objective curve | [`ArgMinExample`](https://docs.manim.community/en/stable/examples.html#argminexample) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Turn an abstract operation into a visible search |
| Geometric invariant | [`PolygonOnAxes`](https://docs.manim.community/en/stable/examples.html#polygononaxes) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Show a quantity staying fixed while inputs change |
| Circle-to-wave mapping | [`SineCurveUnitCircle`](https://docs.manim.community/en/stable/examples.html#sinecurveunitcircle) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/docs/source/examples.rst) | MIT | Make a graph arise from a mechanism |
| Directed process diagram | [`MovingDiGraph`](https://docs.manim.community/en/stable/reference/manim.mobject.graph.DiGraph.html#movingdigraph) in the [official gallery](https://github.com/ManimCommunity/manim/blob/v0.21.0/manim/mobject/graph.py) | MIT | Preserve topology while signaling flow |
| Geometric derivation with narration | [`ApproximatingTau`](https://github.com/ManimCommunity/manim-voiceover/blob/3dc0d95d2f1d9d0937872b3dd68c7b38c4dfc96a/examples/approximating-tau.py) | MIT | Hook, local construction, formula, convergence |

## Adaptation Rules

- Prefer the causal grammar: object -> operation -> visible consequence -> equation.
- Use `TransformMatchingTex` only in raw fallback codegen and isolate semantic TeX fragments with double braces.
- In spec mode, express the same idea with `add_equation`, `transform`, `add_axes`, `add_shape`, `connect`, `label`, `animate`, and `wait`.
- Use `ValueTracker` and updaters only for raw fallback scenes where a moving relationship is essential; keep spec scenes deterministic.
- Reveal an invariant after the viewer has seen the changing quantities, not before.
- For process diagrams, introduce nodes first, then edges, then send one signal along the path.
- Keep one focal relationship per beat and remove obsolete objects before the next relationship.
- Treat official gallery code as Manim CE 0.21 guidance. Do not copy legacy ManimGL APIs such as `ShowCreation`, `TexText`, or `Axes.get_graph`.
