# AniMind — Video Quality Notes

Findings from generated videos, tracked for iteration. Target metrics:
>80% scenes render unaided; visuals match narration; no static stretches >4s.

## Iteration 0 — first E2E run (compounding interest, 2026-08-25)

Observed in `scene_final.mp4` (24s scene):
- [x] Pipeline mechanics work: render OK after 2 attempts, TTS synced, duration matched
- [ ] **Sparse visuals**: single bare circle fills most of the runtime; storyboard asked
      for penny + timeline + growing coins but code delivered only the coin
- [ ] **No persistent context**: title fades out early; viewer loses orientation
- [ ] **Pacing**: static stretches >8s with no new element or motion
- [ ] Colors OK (dark bg, blue accent) — house style partially followed

### Iteration 1 findings (immune memory scene, muted+captions run)
- [x] Muted fallback works: TTS 429 -> captions burned in, freeze-frame extends to narration length
- [x] Visual density improved: split-screen composition, multiple elements
- [ ] **Title/label overlap**: "Innate"/"Adaptive" labels collide with title at top — layout rules need tooth (add: "never place mobjects within 1.0 units of the title")
- [ ] Right half empty at start of split-screen (timing beats not synchronized with narration)
- [ ] Caption chunks cut mid-clause (minor; group by sentence later)

### Root causes & fixes applied to prompts (iteration 1)
1. Coder prompt under-specified density → added rules:
   - "Introduce or animate something new at least every 4–6 seconds"
   - "Keep the title visible for the whole scene"
   - "Visualize EVERY clause of the narration; if narration mentions N things, N visual groups must appear"
   - "Shapes alone are not enough: pair each shape with a short label or equation"

### Planned (v1.5)
- Vision feedback loop: extract start/mid/end frames -> Llama-4 Scout -> layout/density critique -> regenerate (biggest lever per research)
- Few-shot library expanded with dense, multi-element scenes
- Per-scene quality score (frame-diff heuristic: penalize low frame variance) as auto-retry signal
