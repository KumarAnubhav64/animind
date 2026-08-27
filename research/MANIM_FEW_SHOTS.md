# AniMind Few-Shot References

Curated on 2026-08-27 for Manim Community Edition 0.21.0. The code patterns below
are reviewed adaptations, not verbatim copies. Source links and licenses are kept
separate so prompt examples do not blur provenance.

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
