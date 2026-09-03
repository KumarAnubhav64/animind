"""Verified reference database: exact formulas, constants, and facts for
common explainer-video topics, injected into codegen prompts just-in-time.

Why: LLMs frequently misremember formulas and parameter values (the wrong
Greek letter, a dropped term, wrong constants). A deterministic, hand-verified
lookup beats web-scraped snippets for EXACTNESS, costs no API tokens beyond a
small injection block, and works offline.

Usage:
    block = lookup_reference("the Lorenz system chaos")   # -> str | None
The returned block is safe to append to any user prompt; entries are compact
(~100-150 tokens each) and at most two entries are returned.
"""

import re

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceEntry:
    slug: str
    keywords: tuple[str, ...]
    heading: str
    formulas: tuple[str, ...] = field(default_factory=tuple)
    parameters: tuple[str, ...] = field(default_factory=tuple)
    facts: tuple[str, ...] = field(default_factory=tuple)
    plot_hints: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        lines = [f"# {self.heading}"]
        if self.formulas:
            lines.append("Formulas (LaTeX — double-escape backslashes in the spec's tex field):")
            lines.extend(f"- {f}" for f in self.formulas)
        if self.parameters:
            lines.append("Parameters / constants:")
            lines.extend(f"- {p}" for p in self.parameters)
        if self.facts:
            lines.append("Facts (only claim these in the narration visuals):")
            lines.extend(f"- {f}" for f in self.facts)
        if self.plot_hints:
            lines.append("Plot hints:")
            lines.extend(f"- {p}" for p in self.plot_hints)
        return "\n".join(lines)


# Hand-verified entries. LaTeX below is written as the RENDERED form (single
# backslash); the block header tells the model to double-escape for JSON.
ENTRIES: tuple[ReferenceEntry, ...] = (
    ReferenceEntry(
        slug="lorenz",
        keywords=("lorenz", "chaos", "chaotic", "strange attractor", "butterfly attractor", "attractor"),
        heading="Lorenz system (chaotic convection model)",
        formulas=(
            "dx/dt = \\sigma (y - x)",
            "dy/dt = x (\\rho - z) - y",
            "dz/dt = x y - \\beta z",
        ),
        parameters=(
            "Classic values: \\sigma = 10, \\rho = 28, \\beta = 8/3",
            "x ∝ convective intensity, y ∝ temperature difference, z ∝ vertical temperature gradient",
        ),
        facts=(
            "Chaotic for the classic parameters: bounded, non-periodic orbits",
            "Sensitive dependence on initial conditions (nearby trajectories diverge exponentially)",
            "Fully DETERMINISTIC — chaos is not randomness",
        ),
        plot_hints=("the attractor's two 'wings' are centered near x ≈ ±8.5, z ≈ 27"),
    ),
    ReferenceEntry(
        slug="pendulum",
        keywords=("pendulum", "swing", "oscillat"),
        heading="Simple pendulum",
        formulas=(
            "\\theta'' + \\frac{g}{L} \\sin\\theta = 0",
            "Small-angle period: T = 2\\pi \\sqrt{L / g}",
        ),
        parameters=("g = 9.8 m/s² (Earth surface)",),
        facts=(
            "Small-angle approximation (sin θ ≈ θ) is only valid for θ ≲ 15°",
            "Period is independent of mass and (approximately) of amplitude",
        ),
    ),
    ReferenceEntry(
        slug="shm",
        keywords=("simple harmonic", "shm", "spring", "mass-spring", "hooke"),
        heading="Simple harmonic motion (mass-spring)",
        formulas=(
            "F = -k x",
            "\\omega = \\sqrt{k / m},  T = 2\\pi \\sqrt{m / k}",
            "x(t) = A \\cos(\\omega t + \\phi)",
        ),
        parameters=("k = spring constant, m = mass, A = amplitude",),
        facts=(
            "Energy oscillates between kinetic (½mv²) and potential (½kx²); the total is constant",
        ),
        plot_hints=("plot x(t) = cos(t) style sinusoids; velocity leads position by a quarter period"),
    ),
    ReferenceEntry(
        slug="waves",
        keywords=("wave", "wavelength", "frequency", "sound", "light wave", "interference", "diffraction"),
        heading="Waves",
        formulas=(
            "v = f \\lambda",
            "T = 1 / f",
            "Double slit: d \\sin\\theta = m \\lambda",
        ),
        parameters=("sound in air ≈ 343 m/s, light in vacuum = 3\\times10^8 m/s",),
        facts=(
            "Constructive interference when path difference is mλ; destructive at (m + ½)λ",
        ),
        plot_hints=("sin(x) and sin(2x) share one axes to show frequency doubling",),
    ),
    ReferenceEntry(
        slug="fourier",
        keywords=("fourier", "frequency domain", "signal", "harmonic"),
        heading="Fourier series",
        formulas=(
            "f(t) = \\sum_{n} a_n \\cos(n \\omega t) + b_n \\sin(n \\omega t)",
            "Square wave: \\frac{4}{\\pi} \\left(\\sin t + \\tfrac{1}{3}\\sin 3t + \\tfrac{1}{5}\\sin 5t + \\cdots\\right)",
        ),
        facts=(
            "Any periodic signal is a sum of sinusoids at integer multiples of the base frequency",
            "More terms → sharper corners (the Gibbs overshoot never fully vanishes)",
        ),
        plot_hints=("sum sin(x) + sin(3x)/3 + sin(5x)/5 on one axes to build a square wave",),
    ),
    ReferenceEntry(
        slug="gravity",
        keywords=("gravity", "gravitation", "free fall", "orbit", "kepler", "planet", "escape velocity"),
        heading="Gravity and orbits",
        formulas=(
            "F = G \\frac{m_1 m_2}{r^2}",
            "Orbital (circular): v = \\sqrt{G M / r},  T^2 = \\frac{4\\pi^2 r^3}{G M}",
            "Escape velocity: v_e = \\sqrt{2 G M / r}",
        ),
        parameters=("g = 9.8 m/s² at Earth's surface", "G = 6.674\\times10^{-11} N m²/kg²"),
        facts=(
            "Free-fall distance from rest: d = ½ g t² (no air resistance)",
            "Kepler's third law: T² ∝ a³ — farther orbits are slower AND longer",
        ),
    ),
    ReferenceEntry(
        slug="calculus-derivative",
        keywords=("derivative", "differentiat", "tangent", "rate of change", "slope of"),
        heading="Derivatives",
        formulas=(
            "f'(x) = \\lim_{h \\to 0} \\frac{f(x+h) - f(x)}{h}",
            "\\frac{d}{dx} x^n = n x^{n-1}",
            "Product rule: (uv)' = u'v + uv'",
            "Chain rule: (f(g(x)))' = f'(g(x)) g'(x)",
        ),
        facts=(
            "The derivative is the slope of the tangent line — the instantaneous rate of change",
            "At a maximum/minimum the derivative is zero (the tangent is horizontal)",
        ),
        plot_hints=("plot x²/4 with its tangent line at a point that slides along the curve",),
    ),
    ReferenceEntry(
        slug="calculus-integral",
        keywords=("integral", "integrat", "area under", "antiderivative", "riemann"),
        heading="Integrals",
        formulas=(
            "\\int_a^b f(x)\\,dx = \\lim_{n \\to \\infty} \\sum f(x_i) \\Delta x",
            "\\int x^n dx = \\frac{x^{n+1}}{n+1} + C  (n \\neq -1)",
            "Fundamental theorem: \\int_a^b f'(x)\\,dx = f(b) - f(a)",
        ),
        facts=(
            "The integral is the signed area under the curve; Riemann rectangles converge to it",
        ),
        plot_hints=("axes.get_riemann_rectangles over a plotted curve shows the rectangle sum",),
    ),
    ReferenceEntry(
        slug="trig",
        keywords=("pythagorean", "trigonometr", "sin", "cos", "unit circle", "hypotenuse", "sohcahtoa"),
        heading="Trigonometry and the unit circle",
        formulas=(
            "a^2 + b^2 = c^2",
            "\\sin^2\\theta + \\cos^2\\theta = 1",
            "e^{i\\theta} = \\cos\\theta + i\\sin\\theta  (Euler's formula)",
        ),
        facts=(
            "On the unit circle, (cos θ, sin θ) is the point at angle θ",
            "sin and cos are the same curve shifted by π/2",
        ),
    ),
    ReferenceEntry(
        slug="exp-growth",
        keywords=("compound interest", "exponential growth", "exponential decay", "half-life", "e = mc", "population growth"),
        heading="Exponential growth and decay",
        formulas=(
            "A = P (1 + r/n)^{nt}",
            "Continuous: A = P e^{rt}",
            "Decay / half-life: N(t) = N_0 e^{-\\lambda t},  t_{1/2} = \\ln 2 / \\lambda",
        ),
        facts=(
            "Doubling time ≈ 70 / (percent rate) — the rule of 70",
            "Exponential growth beats any polynomial in the long run",
        ),
        plot_hints=("plot exp(0.1x) vs x² on one axes to show the crossover",),
    ),
    ReferenceEntry(
        slug="probability",
        keywords=("probability", "normal distribution", "gaussian", "bell curve", "standard deviation", "statistics", "mean"),
        heading="Probability and the normal distribution",
        formulas=(
            "P(A \\mid B) = \\frac{P(B \\mid A) P(A)}{P(B)}",
            "Normal pdf: f(x) = \\frac{1}{\\sigma\\sqrt{2\\pi}} e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}",
        ),
        facts=(
            "68-95-99.7 rule: the share of data within 1, 2, 3 standard deviations of the mean",
        ),
        plot_hints=("plot exp(-x²/2) for the bell curve; shade ±1σ",),
    ),
    ReferenceEntry(
        slug="neural-net",
        keywords=("neural network", "gradient descent", "machine learning", "backprop", "deep learning", "loss"),
        heading="Neural networks and gradient descent",
        formulas=(
            "z = w \\cdot x + b,  a = \\sigma(z)",
            "\\sigma(z) = \\frac{1}{1 + e^{-z}}",
            "Update: w \\leftarrow w - \\eta \\nabla_w L",
        ),
        parameters=("η (learning rate) is small, e.g. 0.01",),
        facts=(
            "Gradient descent follows the steepest downhill direction of the loss surface",
            "Backpropagation is the chain rule applied layer by layer",
        ),
        plot_hints=("plot (x-2)² with a dot sliding toward the minimum",),
    ),
    ReferenceEntry(
        slug="special-relativity",
        keywords=("relativity", "lorentz factor", "time dilation", "einstein", "spacetime"),
        heading="Special relativity",
        formulas=(
            "\\gamma = \\frac{1}{\\sqrt{1 - v^2/c^2}}",
            "Time dilation: \\Delta t = \\gamma \\Delta t_0",
            "E = \\gamma m c^2",
        ),
        parameters=("c = 3\\times10^8 m/s",),
        facts=(
            "γ ≥ 1 always; γ blows up as v → c",
            "Nothing with mass reaches c — the energy required diverges",
        ),
    ),
    ReferenceEntry(
        slug="thermodynamics",
        keywords=("thermodynamic", "entropy", "ideal gas", "heat engine", "carnot", "second law"),
        heading="Thermodynamics",
        formulas=(
            "PV = n R T",
            "\\Delta S \\ge 0 (isolated systems)",
            "Carnot efficiency: \\eta = 1 - T_c / T_h",
        ),
        parameters=("R = 8.314 J/(mol·K)",),
        facts=(
            "Entropy of an isolated system never decreases — disorder grows",
            "No engine beats the Carnot efficiency between two temperatures",
        ),
    ),
    ReferenceEntry(
        slug="quantum",
        keywords=("quantum", "schrodinger", "photoelectric", "wave function", "uncertainty", "photon"),
        heading="Quantum mechanics essentials",
        formulas=(
            "E = h f  (photon energy)",
            "i\\hbar \\frac{\\partial}{\\partial t}\\Psi = \\hat{H}\\Psi",
            "\\sigma_x \\sigma_p \\ge \\hbar / 2",
        ),
        parameters=("h = 6.626\\times10^{-34} J·s",),
        facts=(
            "Photoelectric effect: below the threshold frequency NO electrons are emitted, however bright the light",
            "The wave function's squared magnitude is a probability density",
        ),
    ),
    ReferenceEntry(
        slug="em",
        keywords=("maxwell", "electromagnetic", "coulomb", "electric field", "magnetic", "faraday", "ampere"),
        heading="Electromagnetism",
        formulas=(
            "Coulomb: F = k_e \\frac{q_1 q_2}{r^2}",
            "Faraday: \\varepsilon = -\\frac{d\\Phi_B}{dt}",
            "Light: c = 1/\\sqrt{\\mu_0 \\varepsilon_0}",
        ),
        parameters=("k_e = 8.99\\times10^9 N m²/C²",),
        facts=(
            "Maxwell's equations predicted light as a self-sustaining EM wave",
            "A changing magnetic field creates an electric field (induction) — that is how generators work",
        ),
    ),
    ReferenceEntry(
        slug="em-wave",
        keywords=("electromagnetic wave", "em wave", "e field", "b field", "propagation direction", "polarization", "wave propagation"),
        heading="Electromagnetic wave visualization (2D depiction)",
        formulas=(
            "E = E_0 \\sin(kx - \\omega t)  (electric field oscillates vertically)",
            "B = B_0 \\sin(kx - \\omega t)  (magnetic field oscillates horizontally, perpendicular to E)",
            "k (propagation direction) is perpendicular to both E and B",
        ),
        parameters=(
            "E and B fields are perpendicular to each other AND to the propagation direction k",
            "In the classic 2D side-view: E points UP/DOWN, B points IN/OUT of screen (shown as left/right arrows), k points RIGHT",
        ),
        facts=(
            "An EM wave is self-sustaining: a changing E creates B, and a changing B creates E",
            "In vacuum, E and B are in phase (peak together) and travel at speed c",
            "The wave carries energy — E and B fields oscillate perpendicular to the direction of travel",
        ),
        plot_hints=(
            "Depict E as a VERTICAL arrow (up/down oscillation along propagation axis)",
            "Depict B as a HORIZONTAL arrow perpendicular to E (left/right, representing into/out of screen)",
            "Show k (propagation) as a RIGHTWARD arrow along the x-axis",
            "Use shape 'arrow' with direction 'up' for E, 'right' for k; rotate B arrow 90° for horizontal",
            "The classic 2D diagram: axes along x (propagation), y (E field), with E sine curve and B as dots/crosses",
            "For a simple static diagram: place E arrow pointing up, B arrow pointing right, k arrow pointing right — label each",
        ),
    ),
    ReferenceEntry(
        slug="momentum",
        keywords=("momentum", "collision", "impulse", "conservation of momentum", "newton's", "force"),
        heading="Momentum and Newton's laws",
        formulas=(
            "p = m v",
            "F = m a = dp/dt",
            "Impulse: J = F \\Delta t = \\Delta p",
            "Elastic collision (equal masses swap): v_1 \\leftrightarrow v_2",
        ),
        facts=(
            "Momentum is conserved in EVERY collision (elastic or not); kinetic energy only in elastic ones",
        ),
    ),
    ReferenceEntry(
        slug="circular-motion",
        keywords=("circular motion", "centripetal", "angular velocity", "rotation speed", "rpm"),
        heading="Circular motion",
        formulas=(
            "a_c = \\frac{v^2}{r} = \\omega^2 r",
            "v = \\omega r",
            "Period: T = 2\\pi / \\omega",
        ),
        facts=(
            "Centripetal acceleration points TO THE CENTER — there is no outward 'centrifugal force' in an inertial frame",
        ),
    ),
)

_ENTRY_INDEX = {entry.slug: entry for entry in ENTRIES}
# Slugs that must NOT win the keyword match when a more specific entry matched.
_BROAD_SLUGS = {"lorenz"}  # "chaos" is a lorenz keyword but also generic

_WORD_RE = re.compile(r"[a-z0-9']+")


def _score(entry: ReferenceEntry, text_lower: str, tokens: set[str]) -> int:
    score = 0
    for kw in entry.keywords:
        if " " in kw:
            if kw in text_lower:
                score += 3  # multi-word phrases are strong signals
        elif kw in tokens:
            score += 1
    # A direct slug/heading mention is the strongest signal.
    if entry.slug.replace("-", " ") in text_lower or entry.heading.lower() in text_lower:
        score += 5
    return score


def lookup_reference(*texts: str, max_entries: int = 2) -> str | None:
    """Return a compact grounding block for the best-matching entries, or None.

    Matches on the union of the provided texts (topic + title + narration).
    Falls back to nothing when no entry scores — never invents content.
    """
    text_lower = " ".join(t for t in texts if t).lower()
    if not text_lower.strip():
        return None
    tokens = set(_WORD_RE.findall(text_lower))
    scored = sorted(
        ((score, entry) for entry in ENTRIES if (score := _score(entry, text_lower, tokens)) > 0),
        key=lambda pair: -pair[0],
    )
    if not scored:
        return None
    picked: list[ReferenceEntry] = []
    for score, entry in scored:
        if len(picked) >= max_entries:
            break
        # Skip generic entries that scored only via broad words when a
        # specific entry already matched strongly.
        if entry.slug in _BROAD_SLUGS and score < 2 and picked:
            continue
        picked.append(entry)
    if not picked:
        return None
    blocks = [entry.render() for entry in picked]
    header = (
        "VERIFIED REFERENCE DATA (authoritative — use these EXACT formulas, "
        "symbols, and values; do NOT re-derive or substitute your own):"
    )
    return header + "\n" + "\n\n".join(blocks)


def get_entry(slug: str) -> ReferenceEntry | None:
    return _ENTRY_INDEX.get(slug)
