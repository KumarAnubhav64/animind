"""Condensed Mayer multimedia-learning principles for prompt embedding.

Source: Richard E. Mayer, *Multimedia Learning* 3rd ed. (2021); distilled
from controlled experiments across 200+ studies.  Keep this block under
~200 tokens so it does not crowd out the main prompt.
"""

MAYER_PRINCIPLES = """\
MAYER'S MULTIMEDIA LEARNING PRINCIPLES (evidence-based, apply to every scene):

Goal 1 — Reduce extraneous processing:
- Coherence: remove anything that does not directly support the current idea.
  No decorative shapes, no background music, no filler text.
- Signaling: highlight what matters right now — use Indicate/Circumscribe on
  the object the narration is about; grey-out or remove everything else.
- Redundancy: do NOT show the same text on screen AND narrate it.  If the
  narration says the word, the visual should SHOW the concept, not repeat the
  word.  The only on-screen text is labels, equations, or short titles.

Goal 2 — Manage essential processing:
- Segmenting: one idea per beat.  If the narration says "A then B", split into
  two beats.  Never stack two ideas in the same beat.
- Pre-training: when a new concept appears, name it BEFORE diving into its
  behaviour.  Beat 1 = introduce element.  Beat 2 = animate it.
- Modality: narration + animated visual (not narration + on-screen paragraph).
  The voice carries the explanation; the visual carries the evidence.

Goal 3 — Foster generative processing:
- Spatial contiguity: labels MUST be adjacent to the object they describe
  (use the label op, direction toward the object).  Never place a label far
  from its referent.
- Temporal contiguity: the visual must appear WHEN the narration mentions it,
  not before or after.  Pace beats so the animation lands with the spoken idea.
- Multimedia: pair every verbal claim with a visual counterpart.  A number in
  narration → bars or equation on screen.  A process → arrows.  A comparison →
  left vs right.
- Personalization: narration should use conversational language ("we", "you",
  "notice how...") not formal textbook prose.
"""
