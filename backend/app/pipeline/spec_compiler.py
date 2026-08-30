"""SceneSpec -> Manim code compiler.

Deterministic, house-style-by-construction code generation. The LLM never
writes Manim directly in spec mode, so: no hallucinated APIs, no layout
collisions, no missing imports, consistent timing.
"""

import json
import math
import textwrap
from pathlib import Path

from app.schemas.spec import SceneSpec, SpecAction

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

COLORS = {
    "blue": "BLUE", "red": "RED", "green": "GREEN", "yellow": "YELLOW",
    "teal": "TEAL", "purple": "PURPLE", "orange": "ORANGE", "gold": "GOLD",
    "white": "WHITE", "grey": "GREY_B", "gray": "GREY_B", "pink": "PINK",
}

# Content band anchors (title owns the top edge, y >= 2.4 is off-limits).
# Each anchor is a REGION BOX: (center_x, center_y, half_width, half_height).
REGIONS = {
    "center": (0.0, -0.4, 3.0, 1.7),
    "left": (-3.4, -0.4, 2.6, 1.9),
    "right": (3.4, -0.4, 2.6, 1.9),
    "top": (0.0, 1.4, 4.5, 0.9),
    "bottom": (0.0, -1.9, 4.5, 0.7),
    "top_left": (-3.4, 1.3, 2.6, 0.9),
    "top_right": (3.4, 1.3, 2.6, 0.9),
    "bottom_left": (-3.4, -1.9, 2.6, 0.7),
    "bottom_right": (3.4, -1.9, 2.6, 0.7),
}

# In-region slot offsets as fractions of (half_width, half_height): a 3x3 grid
# ordered center -> ring, so repeated placements never stack exactly on top of
# each other (the #1 layout failure of freeform generation).
_SLOT_GRID = [
    (0.0, 0.0),
    (-0.62, 0.0), (0.62, 0.0),
    (0.0, -0.55), (0.0, 0.55),
    (-0.62, -0.55), (0.62, -0.55), (-0.62, 0.55), (0.62, 0.55),
]

DIRECTIONS = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT"}

SHAPES_2D = {"circle", "square", "dot", "triangle", "diamond", "ring"}
SHAPES_3D = {"sphere", "cube", "cylinder", "cone", "torus"}
SHAPES = SHAPES_2D | SHAPES_3D

DEFAULT_ANIM = {"add_text": "write", "add_equation": "write", "add_shape": "grow",
                "add_axes": "create", "add_bars": "create", "label": "write",
                "connect": "create", "set_title": "write"}


def _var(mobject_id: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in mobject_id)
    return f"m_{safe}"


def _clean(s: str | None) -> str:
    """Flatten whitespace/newlines and strip Unicode control characters."""
    if s is None:
        return ""
    text = " ".join(str(s).split()).strip()
    # Remove Unicode control chars (except newline/tab) that break Manim Text()
    return "".join(c for c in text if ord(c) >= 32 or c in "\n\t")


def _literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _wrapped_text(value: str, region: str | None) -> str:
    region = (region or "center").lower()
    width = 28 if region in {"left", "right", "top_left", "top_right", "bottom_left", "bottom_right"} else 48
    return "\n".join(
        textwrap.wrap(value, width=width, break_long_words=False, break_on_hyphens=False)
    ) or value


_PLOT_ALLOWED = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "pi", "e"}


def _safe_expr(expr: str) -> str:
    """Plot expressions must be valid python(x). Undefined names (LaTeX-style
    constants like C0 or k) are replaced with 1 so the curve always renders."""
    import ast
    import re

    expr = _clean(expr)
    try:
        tree = ast.parse(expr, mode="eval")
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    except SyntaxError:
        return "x"
    out = expr
    for name in sorted(names - _PLOT_ALLOWED, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(name)}\b", "(1)", out)
    return out


def _color(color: str | None, default: str = "WHITE") -> str:
    return COLORS.get((color or "").lower(), default)


class SpecCompiler:
    def __init__(self, spec: SceneSpec, target_duration: float | None = None):
        self.spec = spec
        self.target = target_duration
        self.lines: list[str] = []
        self.known: set[str] = set()
        self.duration = 0.0
        self.slots_used: dict[str, int] = {}  # region -> placements so far
        # Approximate centers and regions of placed mobjects for label routing.
        self.boxes: dict[str, tuple[float, float]] = {}
        self.regions: dict[str, str] = {}
        # Bounding-box half-extents for overlap detection: id -> (half_w, half_h)
        self.bbox_extents: dict[str, tuple[float, float]] = {}
        self.visual_count = 0
        self.use_3d = False  # auto-set when 3D shapes are used
        self.axes_ids: set[str] = set()  # ids created via add_axes (valid add_curve targets)

    # ---------------------------------------------------------------- helpers

    def emit(self, line: str, run_time: float = 0.0):
        self.lines.append("        " + line)
        self.duration += run_time

    def _bbox_half_extents(self, action: SpecAction) -> tuple[float, float]:
        """Estimate half-width and half-height of an action's bounding box."""
        op = action.op
        scale = action.scale or 1.0
        if op == "add_shape":
            shape = (action.shape or "circle").lower()
            if shape in {"dot"}:
                return 0.2 * scale, 0.2 * scale
            if shape in {"ring"}:
                return 0.95 * scale, 0.95 * scale
            if shape in {"sphere", "cube", "cylinder", "cone", "torus"}:
                return 0.95 * scale, 0.95 * scale
            base = 1.0 * scale
            if not (action.at and len(action.at) >= 2):
                # Region-placed shapes grow to fill the region (see _fit fill).
                _, _, hw, hh = REGIONS.get((action.region or "center").lower(), REGIONS["center"])
                base = max(base, min(2 * hw - 0.45, 2 * hh - 0.35) / 2.0)
            return base, base  # circle, square, triangle, diamond
        if op == "add_asset":
            base = 0.6 * scale
            if not (action.at and len(action.at) >= 2):
                _, _, hw, hh = REGIONS.get((action.region or "center").lower(), REGIONS["center"])
                base = max(base, min(2 * hw - 0.45, 2 * hh - 0.35) / 2.0)
            return base, base
        if op in {"add_axes", "add_bars"}:
            return 1.8, 1.4
        if op == "add_char_table":
            return 5.0, 3.0
        # text / equation / label: estimate from content length
        content = action.text or action.tex or ""
        font_size = 44 if op == "add_equation" else 30
        # rough char width: font_size * 0.006 at scale 1
        char_w = font_size * 0.006
        half_w = min(len(content) * char_w * 0.5, 4.0) + 0.3
        half_h = 0.35 if op == "add_equation" else 0.25
        return half_w, half_h

    def _overlaps_any(
        self, cx: float, cy: float, hw: float, hh: float, skip_id: str = ""
    ) -> bool:
        """Check if a proposed box overlaps any already-placed bounding box."""
        pad = 0.25  # minimum clearance between objects
        for oid, (ox, oy) in self.boxes.items():
            if oid == skip_id:
                continue
            ow, oh = self.bbox_extents.get(oid, (0.5, 0.5))
            # AABB overlap test
            if (
                abs(cx - ox) < (hw + ow + pad)
                and abs(cy - oy) < (hh + oh + pad)
            ):
                return True
        return False

    def _find_free_position(
        self, x: float, y: float, hw: float, hh: float, region: str
    ) -> tuple[float, float]:
        """Search for the nearest non-overlapping position within the region."""
        if not self._overlaps_any(x, y, hw, hh):
            return x, y
        cx, cy, r_hw, r_hh = REGIONS.get(region.lower(), REGIONS["center"])
        # Search in an expanding spiral from the requested position
        for radius in (0.8, 1.5, 2.2, 3.0):
            for angle_deg in range(0, 360, 30):
                angle = math.radians(angle_deg)
                nx = x + radius * math.cos(angle)
                ny = y + radius * math.sin(angle)
                # Clamp within region bounds
                nx = max(cx - r_hw, min(nx, cx + r_hw))
                ny = max(cy - r_hh, min(ny, cy + r_hh))
                nx, ny = self._clamp(nx, ny, SpecAction(op="add_text"))
                if not self._overlaps_any(nx, ny, hw, hh):
                    return nx, ny
        # Fallback: use the slot system for this region
        return self._slot_position(region)

    def _slot_position(self, region: str) -> tuple[float, float]:
        """Next free position inside a region box (collision-free by design)."""
        cx, cy, hw, hh = REGIONS.get(region.lower(), REGIONS["center"])
        n = self.slots_used.get(region.lower(), 0)
        self.slots_used[region.lower()] = n + 1
        fx, fy = _SLOT_GRID[n % len(_SLOT_GRID)]
        return cx + fx * hw * 2 / 3, cy + fy * hh * 2 / 3

    def _position(self, action: SpecAction) -> tuple[str, float, float]:
        hw, hh = self._bbox_half_extents(action)
        if action.at and len(action.at) >= 2:
            x, y = self._clamp(action.at[0], action.at[1], action)
            # Check overlap with existing objects and find free position
            region = action.region or "center"
            x, y = self._find_free_position(x, y, hw, hh, region)
            return f"move_to([{x:.2f}, {y:.2f}, 0])", x, y
        x, y = self._slot_position(action.region or "center")
        x, y = self._clamp(x, y, action)
        return f"move_to([{x:.2f}, {y:.2f}, 0])", x, y

    def _region_limits(self, region: str | None) -> tuple[float, float]:
        _cx, _cy, hw, hh = REGIONS.get((region or "center").lower(), REGIONS["center"])
        return max(1.2, 2 * hw - 0.45), max(0.7, 2 * hh - 0.35)

    def _fit_and_place(self, var: str, action: SpecAction) -> tuple[float, float]:
        """Fit object to region limits and place it, storing bbox for overlap detection."""
        # When explicit coordinates are given, use full-frame limits (objects
        # are placed intentionally — don't shrink them to region bounds).
        if action.at and len(action.at) >= 2:
            # Text elements need tighter width limits to prevent edge cutoff
            max_width = 11.0 if action.op in ("add_text", "add_equation") else 13.5
            max_height = 7.0
        else:
            max_width, max_height = self._region_limits(action.region)
        # Region-placed geometric shapes grow to fill their region (the hero
        # diagram should dominate, not sit as a small accent). Dots stay small —
        # they are markers. Explicit at:[x,y] keeps the author's intended size.
        fill = (
            action.op in ("add_shape", "add_asset")
            and not (action.at and len(action.at) >= 2)
            and (action.shape or "circle").lower() != "dot"
        )
        self.emit(
            f"_fit({var}, {max_width:.2f}, {max_height:.2f}{', True' if fill else ''})"
        )
        pos_line, x, y = self._position(action)
        self.emit(f"{var}.{pos_line}")
        self.emit(f"_keep_in_frame({var})")
        # Store bounding box for overlap detection on subsequent placements
        if action.id:
            hw, hh = self._bbox_half_extents(action)
            self.bbox_extents[action.id] = (hw, hh)
        return x, y

    def _replace_existing(self, mobject_id: str):
        if mobject_id not in self.known:
            return
        self.emit(f"self.play(FadeOut({_var(mobject_id)}), run_time=0.6)", 0.6)
        self.known.discard(mobject_id)
        self.boxes.pop(mobject_id, None)
        self.regions.pop(mobject_id, None)
        self.bbox_extents.pop(mobject_id, None)

    # Frame is 14.22 x 8 units; title owns everything above y=2.2, and
    # the bottom band (y < -2.5) is where burned-in narration subtitles
    # land, so content must stay above it.
    def _clamp(self, x: float, y: float, action: SpecAction) -> tuple[float, float]:
        op = action.op
        if op == "add_shape":
            margin = 0.9 * (action.scale or 1.0) + 0.6
        elif op == "add_axes" or op == "add_bars":
            margin = 2.8
        else:  # text / equation: estimate half-width from content length
            content = action.text or action.tex or ""
            size = 44 if op == "add_equation" else 30
            margin = min(len(content) * size * 0.004, 4.0) + 0.5
        xmax = max(7.11 - margin, 1.5)
        ymax = max(2.2 - (margin * 0.5), 1.0)
        ymin = -2.5 + (margin * 0.4)
        return min(max(x, -xmax), xmax), min(max(y, ymin), ymax)

    def _anim_line(self, action: SpecAction, expr: str, default_rt: float = 1.0):
        # Multiple mobjects must be wrapped in a VGroup — a bare second
        # positional lands in the animation's run_time slot.
        parts = [p.strip() for p in expr.split(",") if p.strip()]
        target = f"VGroup({', '.join(parts)})" if len(parts) > 1 else expr
        anim = (action.anim or DEFAULT_ANIM.get(action.op, "fade_in")).lower()
        rt = {"write": 2.0, "create": 2.0, "grow": 2.0, "fade_in": 2.0}.get(anim, default_rt)
        anim_map = {
            "write": f"self.play(Write({target}), run_time={rt})",
            "create": f"self.play(Create({target}), run_time={rt})",
            "fade_in": f"self.play(FadeIn({target}), run_time={rt})",
            "grow": f"self.play(GrowFromCenter({target}), run_time={rt})",
        }
        self.emit(anim_map.get(anim, anim_map["fade_in"]), rt)

    # ---------------------------------------------------------------- ops

    def op_set_title(self, a: SpecAction):
        text = _literal(_clean(a.text or self.spec.title))
        self.emit(
            f"title = Text({text}, font_size=36, weight=BOLD)"
        )
        self.emit("_fit(title, 11.0, 0.72)")
        self.emit("title.to_edge(UP, buff=0.3)")
        self.emit("self.play(Write(title), run_time=2.0)", 2.0)

    def op_add_text(self, a: SpecAction):
        if not a.id or a.text is None:
            return
        self._replace_existing(a.id)
        text = _literal(_wrapped_text(_clean(a.text), a.region))
        size = int(30 * (a.scale or 1.0))
        self.emit(
            f"{_var(a.id)} = Text({text}, font_size={size}, color={_color(a.color)})"
        )
        x, y = self._fit_and_place(_var(a.id), a)
        self.boxes[a.id] = (x, y)
        self.regions[a.id] = (a.region or "center").lower()
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id))

    def op_add_equation(self, a: SpecAction):
        if not a.id or a.tex is None:
            return
        self._replace_existing(a.id)
        tex = _literal(_clean(a.tex))
        size = int(44 * (a.scale or 1.0))
        self.emit(
            f"{_var(a.id)} = MathTex({tex}, font_size={size}, color={_color(a.color)})"
        )
        x, y = self._fit_and_place(_var(a.id), a)
        self.boxes[a.id] = (x, y)
        self.regions[a.id] = (a.region or "center").lower()
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id))

    def op_add_shape(self, a: SpecAction):
        if not a.id:
            return
        self._replace_existing(a.id)
        shape = (a.shape or "circle").lower()
        color = _color(a.color, "BLUE")
        scale = a.scale or 1.0
        # 2D shapes
        constructors_2d = {
            "circle": f"Circle(radius=0.9 * {scale:.2f}, color={color})",
            "square": f"Square(side_length=1.6 * {scale:.2f}, color={color})",
            "dot": f"Dot(radius=0.15 * {scale:.2f}, color={color})",
            "triangle": f"Triangle(radius=0.9 * {scale:.2f}, color={color})",
            "diamond": f"Polygon([0,1,0],[1,0,0],[0,-1,0],[-1,0,0], color={color}).scale({scale:.2f})",
            "ring": f"Circle(radius=0.9 * {scale:.2f}, color={color}).set_stroke(width=6)",
        }
        # 3D shapes
        constructors_3d = {
            "sphere": f"Sphere(radius=0.9 * {scale:.2f}, color={color}, resolution=(24, 24))",
            "cube": f"Cube(side_length=1.4 * {scale:.2f}, color={color})",
            "cylinder": f"Cylinder(radius=0.7 * {scale:.2f}, height=1.6 * {scale:.2f}, color={color})",
            "cone": f"Cone(base_radius=0.8 * {scale:.2f}, height=1.6 * {scale:.2f}, color={color})",
            "torus": f"Torus(major_radius=0.8 * {scale:.2f}, minor_radius=0.25 * {scale:.2f}, color={color})",
        }
        if shape in constructors_3d:
            self.use_3d = True
            self.emit(f"{_var(a.id)} = {constructors_3d[shape]}")
        elif shape in constructors_2d:
            self.emit(f"{_var(a.id)} = {constructors_2d[shape]}")
        else:
            self.emit(f"{_var(a.id)} = {constructors_2d['circle']}")
        x, y = self._fit_and_place(_var(a.id), a)
        self.boxes[a.id] = (x, y)
        self.regions[a.id] = (a.region or "center").lower()
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id))

    def op_add_asset(self, a: SpecAction):
        if not a.id:
            return
        self._replace_existing(a.id)
        asset_name = (a.asset or "").lower().replace(" ", "_")
        asset_path = ASSETS_DIR / f"{asset_name}.svg"
        if not asset_path.exists():
            # Fallback to circle if asset not found
            self.emit(f'{_var(a.id)} = Circle(radius=0.5, color={_color(a.color, "BLUE")})')
        else:
            color = _color(a.color, "WHITE")
            self.emit(f'{_var(a.id)} = SVGMobject("{asset_path}").set_color({color})')
        scale = a.scale or 1.0
        if scale != 1.0:
            self.emit(f'{_var(a.id)}.scale({scale:.2f})')
        x, y = self._fit_and_place(_var(a.id), a)
        self.boxes[a.id] = (x, y)
        self.regions[a.id] = (a.region or "center").lower()
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id))

    def op_add_axes(self, a: SpecAction):
        if not a.id:
            return
        self._replace_existing(a.id)
        xr = a.x_range or [-3, 3, 1]
        yr = a.y_range or [-2, 2, 1]
        color = _color(a.color, "WHITE")
        max_width, max_height = self._region_limits(a.region)
        self.emit(
            f"{_var(a.id)} = Axes(x_range={xr!r}, y_range={yr!r}, "
            f"x_length={max_width:.2f}, y_length={max_height:.2f}, "
            f'axis_config={{"include_tip": True, "stroke_width": 2}})'
        )
        # Axes dimensions are already bounded explicitly; fitting the axes
        # object again would also shrink its plotted coordinate system.
        pos_line, x, y = self._position(a)
        self.emit(f"{_var(a.id)}.{pos_line}")
        self.emit(f"_keep_in_frame({_var(a.id)})")
        self.boxes[a.id] = (x, y)
        self.regions[a.id] = (a.region or "center").lower()
        self.axes_ids.add(a.id)
        if a.expr:
            expr = _safe_expr(a.expr)
            self.emit(f"{_var(a.id)}_plot = {_var(a.id)}.plot(lambda x: {expr}, color={color})")
            self.known.add(a.id)
            self._anim_line(a, f"{_var(a.id)}, {_var(a.id)}_plot", default_rt=1.8)
            self.emit(f"{_var(a.id)}_plot.set_color({color})")
            self.emit(f"{_var(a.id)} = VGroup({_var(a.id)}, {_var(a.id)}_plot)")
            self.emit(f"_keep_in_frame({_var(a.id)})")
        else:
            self.known.add(a.id)
            self._anim_line(a, _var(a.id), default_rt=1.5)
        self.visual_count += 1

    def op_add_curve(self, a: SpecAction):
        """Plot a function curve onto an existing axes (the math plotter)."""
        if not a.id or not a.target or a.target not in self.axes_ids:
            return
        self._replace_existing(a.id)
        expr = _safe_expr(a.expr or "0")
        if a.offset:
            offset = float(a.offset)
            sign = "+" if offset >= 0 else "-"
            expr = f"({expr}) {sign} {abs(offset):.2f}"
        color = _color(a.color, "BLUE")
        axes_var = _var(a.target)
        self.emit(f"{_var(a.id)} = {axes_var}.plot(lambda x: {expr}, color={color})")
        self.emit(f"{_var(a.id)}.set_stroke(width=4)")
        # A curve lives inside its axes (data coords); only record a hint box
        # for label routing. Keep it thin so it never scatters other objects.
        tx, ty = self.boxes.get(a.target, (0.0, -0.4))
        self.boxes[a.id] = (tx, ty)
        self.regions[a.id] = self.regions.get(a.target, "center")
        self.bbox_extents[a.id] = (0.1, 0.1)
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id), default_rt=1.8)

    def op_add_bars(self, a: SpecAction):
        if not a.id or not a.values:
            return        self._replace_existing(a.id)
        vals = ", ".join(f"{v:.2f}" for v in a.values)
        color = _color(a.color, "BLUE")
        self.emit(
            f'{_var(a.id)} = BarChart(values=[{vals}], bar_names={[f"{i+1}" for i in range(len(a.values))]}, '
            f"bar_colors=[{color}] * {len(a.values)}, bar_width=0.5)"
        )
        x, y = self._fit_and_place(_var(a.id), a)
        self.boxes[a.id] = (x, y)
        self.regions[a.id] = (a.region or "center").lower()
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id), default_rt=1.8)

    def op_label(self, a: SpecAction):
        if not a.id or a.text is None or not a.target or a.target not in self.known:
            return
        self._replace_existing(a.id)
        text = _literal(_clean(a.text))
        tx, ty = self.boxes.get(a.target, (0.0, -0.4))
        if a.direction:
            direction = DIRECTIONS.get(a.direction.lower(), "DOWN")
        else:
            target_region = self.regions.get(a.target, "center")
            if target_region in {"bottom", "bottom_left", "bottom_right"}:
                direction = "UP"
            else:
                # A horizontal label beside a half-screen diagram tends to
                # land in the center gutter; keep labels below their target.
                direction = "DOWN"
        self.emit(
            f"{_var(a.id)} = Text({text}, font_size=26, color={_color(a.color)})"
        )
        self.emit(f"_fit({_var(a.id)}, 3.8, 0.65)")
        self.emit(f"{_var(a.id)}.next_to({_var(a.target)}, {direction}, buff=0.3)")
        self.emit(f"_fit({_var(a.id)}, 3.8, 0.65)")
        self.emit(f"_keep_in_frame({_var(a.id)})")
        self.boxes[a.id] = (tx, ty)
        self.regions[a.id] = self.regions.get(a.target, "center")
        self.known.add(a.id)
        self._anim_line(a, _var(a.id))

    def op_connect(self, a: SpecAction):
        if not a.id or not a.from_id or not a.to:
            return
        if a.from_id not in self.known or a.to not in self.known:
            return
        color = _color(a.color, "GREY_B")
        # link() picks the facing edges from actual positions — never draws
        # an arrow backwards through a shape
        self.emit(
            f"{_var(a.id)} = link({_var(a.from_id)}, {_var(a.to)}, color={color})"
        )
        ax, ay = self.boxes.get(a.from_id, (0.0, -0.4))
        bx, by = self.boxes.get(a.to, (0.0, -0.4))
        self.boxes[a.id] = ((ax + bx) / 2, (ay + by) / 2)
        self.regions[a.id] = "center"
        self.known.add(a.id)
        self.visual_count += 1
        self._anim_line(a, _var(a.id), default_rt=0.8)

    def op_animate(self, a: SpecAction):
        anim = (a.anim or "indicate").lower()
        if a.target == "all":
            targets = sorted(self.known)
        else:
            targets = [t for t in [a.target] if t and t in self.known]
        if not targets:
            return
        exprs = ", ".join(_var(t) for t in targets)
        target = f"VGroup({exprs})" if len(targets) > 1 else exprs
        anims = {
            "indicate": f"self.play(Indicate({target}), run_time=2.0)",
            "circumscribe": f"self.play(Circumscribe({target}), run_time=2.0)",
            "flash": f"self.play(Flash({target}.get_center()), run_time=1.2)",
            "fade_out": f"self.play(FadeOut({target}), run_time=1.5)",
        }
        if anim in ("fade_out",):
            for t in targets:
                self.known.discard(t)
                self.boxes.pop(t, None)
                self.regions.pop(t, None)
        line = anims.get(anim)
        if line:
            self.emit(line, {"indicate": 2.0, "circumscribe": 2.0, "flash": 1.2, "fade_out": 1.5}[anim])

    def op_transform(self, a: SpecAction):
        if not a.id or a.id not in self.known:
            return
        region = self.regions.get(a.id, "center")
        max_width, max_height = self._region_limits(region)
        if a.tex:
            tex = _literal(_clean(a.tex))
            new = f"{_var(a.id)}_t"
            self.emit(f"{new} = MathTex({tex}, font_size=44)")
        elif a.text is not None:
            text = _literal(_wrapped_text(_clean(a.text), region))
            new = f"{_var(a.id)}_t"
            self.emit(f"{new} = Text({text}, font_size=30)")
        else:
            return
        self.emit(f"_fit({new}, {max_width:.2f}, {max_height:.2f})")
        self.emit(f"{new}.move_to({_var(a.id)})")
        self.emit(f"_keep_in_frame({new})")
        self.emit(f"self.play(Transform({_var(a.id)}, {new}), run_time=2.0)", 2.0)

    def op_move(self, a: SpecAction):
        if not a.id or a.id not in self.known:
            return
        pos_line, x, y = self._position(a)
        rt = min(max(a.seconds or 2.0, 0.2), 8.0)
        self.emit(f"self.play({_var(a.id)}.animate.{pos_line}, run_time={rt:.2f})", rt)
        self.emit(f"_keep_in_frame({_var(a.id)})")
        self.boxes[a.id] = (x, y)

    def op_rotate(self, a: SpecAction):
        """Spin an object: `rotate {id, turns, seconds?}` — continuous motion,
        the basic ingredient of 3B1B-style phasor/diagram movement."""
        if not a.id or a.id not in self.known:
            return
        turns = min(max(a.turns or 1.0, -10.0), 10.0)
        rt = min(max(a.seconds or 2.0, 0.3), 12.0)
        self.emit(
            f"self.play(Rotate({_var(a.id)}, angle=TAU * {turns:.2f}), run_time={rt:.2f}, "
            f"rate_func=linear)",
            rt,
        )

    def op_pulse(self, a: SpecAction):
        """Attention pulse: quick scale up/down of a mobject (or 'all')."""
        if a.target == "all":
            targets = sorted(self.known)
        else:
            targets = [t for t in [a.target] if t and t in self.known]
        if not targets:
            return
        for t in targets:
            self.emit(f"self.play({_var(t)}.animate.scale(1.15), run_time=0.5)", 0.5)
        for t in targets:
            self.emit(f"self.play({_var(t)}.animate.scale(1 / 1.15), run_time=0.5)", 0.5)

    def op_remove(self, a: SpecAction):
        if a.target == "all":
            if self.known:
                exprs = ", ".join(_var(t) for t in sorted(self.known))
                self.emit(f"self.play(FadeOut(VGroup({exprs})), run_time=0.8)", 0.8)
                self.known.clear()
                self.boxes.clear()
                self.regions.clear()
        elif a.target and a.target in self.known:
            self.emit(f"self.play(FadeOut({_var(a.target)}), run_time=1.5)", 1.5)
            self.known.discard(a.target)
            self.boxes.pop(a.target, None)
            self.regions.pop(a.target, None)

    def op_clear(self, a: SpecAction):
        """Explicit canvas clear — like remove all but with a brief pause
        and visual reset. Use this between distinct diagrams."""
        if self.known:
            exprs = ", ".join(_var(t) for t in sorted(self.known))
            self.emit(f"self.play(FadeOut(VGroup({exprs})), run_time=1.0)", 1.0)
        self.emit("self.wait(0.3)", 0.3)
        self.known.clear()
        self.boxes.clear()
        self.regions.clear()
        self.slots_used.clear()

    def op_wait(self, a: SpecAction):
        seconds = min(max(a.seconds or 1.5, 0.0), 20.0)
        self.emit(f"self.wait({seconds:.1f})", seconds)

    # ---------------------------------------------------------------- top level

    def compile(self) -> str:
        ops = {
            "set_title": self.op_set_title, "add_text": self.op_add_text,
            "add_equation": self.op_add_equation, "add_shape": self.op_add_shape,
            "add_asset": self.op_add_asset, "add_axes": self.op_add_axes,
            "add_bars": self.op_add_bars, "add_curve": self.op_add_curve,
            "label": self.op_label, "connect": self.op_connect,
            "animate": self.op_animate, "transform": self.op_transform,
            "move": self.op_move, "rotate": self.op_rotate, "pulse": self.op_pulse,
            "remove": self.op_remove, "clear": self.op_clear, "wait": self.op_wait,
        }
        title_action = next(
            (
                action
                for beat in self.spec.beats
                for action in beat.actions
                if action.op == "set_title"
            ),
            SpecAction(op="set_title", text=self.spec.title),
        )
        self.op_set_title(title_action)
        for beat in self.spec.beats:
            for action in beat.actions:
                if action.op == "set_title":
                    continue
                ops.get(action.op, lambda _a: None)(action)

        if self.visual_count < 3:
            raise ValueError(
                "SceneSpec is underspecified: expected at least 3 meaningful visual elements"
            )

        # Fit total duration to the narration audio (hold final frame if short;
        # if too long the merge step truncates to the audio duration anyway)
        if self.target and self.duration < self.target:
            remaining = self.target - self.duration
            self.emit(f"self.wait({remaining:.1f})  # hold final frame for narration", remaining)

        body = "\n".join(self.lines) or "        pass"

        # Choose Scene vs ThreeDScene based on whether 3D shapes were used
        if self.use_3d:
            scene_class = "ThreeDScene"
            camera_init = (
                '        self.camera.background_color = "#1c1c1c"\n'
                "        self.set_camera_orientation(phi=60 * DEGREES, theta=-45 * DEGREES)\n"
            )
        else:
            scene_class = "Scene"
            camera_init = '        self.camera.background_color = "#1c1c1c"\n'

        return (
            "from manim import *\n"
            "from math import sin, cos, tan, exp, log, sqrt, pi\n"
            "e = exp(1)\n\n\n"
            "def _fit(m, max_width, max_height, fill=False):\n"
            "    if m.width > max_width:\n"
            "        m.scale_to_fit_width(max_width)\n"
            "    if m.height > max_height:\n"
            "        m.scale_to_fit_height(max_height)\n"
            "    if fill:\n"
            "        s = min(max_width / m.width, max_height / m.height)\n"
            "        if s > 1.0:\n"
            "            m.scale(s)\n"
            "    return m\n\n\n"
            "def _keep_in_frame(m):\n"
            "    left, right, bottom, top = -6.75, 6.75, -2.5, 2.1\n"
            "    dx = left - m.get_left()[0] if m.get_left()[0] < left else 0\n"
            "    if m.get_right()[0] + dx > right:\n"
            "        dx += right - (m.get_right()[0] + dx)\n"
            "    dy = bottom - m.get_bottom()[1] if m.get_bottom()[1] < bottom else 0\n"
            "    if m.get_top()[1] + dy > top:\n"
            "        dy += top - (m.get_top()[1] + dy)\n"
            "    m.shift([dx, dy, 0])\n"
            "    return m\n\n\n"
            "def link(a, b, color=GREY_B):\n"
            "    ca, cb = a.get_center(), b.get_center()\n"
            "    if abs(cb[0] - ca[0]) >= abs(cb[1] - ca[1]):\n"
            "        right = cb[0] > ca[0]\n"
            "        return Arrow(a.get_edge_center(RIGHT if right else LEFT), "
            "b.get_edge_center(LEFT if right else RIGHT), buff=0.15, stroke_width=3, color=color)\n"
            "    up = cb[1] > ca[1]\n"
            "    return Arrow(a.get_edge_center(UP if up else DOWN), "
            "b.get_edge_center(DOWN if up else UP), buff=0.15, stroke_width=3, color=color)\n\n\n"
            f"class VideoScene({scene_class}):\n"
            "    def construct(self):\n"
            f"{camera_init}"
            f"{body}\n"
        )


def compile_spec(spec: SceneSpec, target_duration: float | None = None) -> str:
    return SpecCompiler(spec, target_duration).compile()
