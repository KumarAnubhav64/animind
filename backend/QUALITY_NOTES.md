
## Spec-mode codegen (Aug 26, 2026)
- New default path: LLM emits declarative SceneSpec JSON -> `pipeline/spec_compiler.py`
  deterministically writes Manim code. House style/layout guaranteed by construction;
  ~5x fewer output tokens; no hallucinated APIs.
- Fallback chain: spec render fail -> raw LLM codegen + RITL (verified live twice).
- Compiler hardening learned from failures:
  - multi-mobject animations must be VGroup-wrapped (bare 2nd positional lands in run_time)
  - `_clean()` flattens newlines/quotes before embedding text/tex in code lines
  - `_safe_expr()` AST-strips undefined names (LaTeX-style C0/k) from plot exprs
  - math preamble (sin/cos/exp/e/pi) for plot expressions
- Groq json_schema is flaky on big/nested schemas (~2/3 SceneSpec calls 400
  json_validate_failed); structured_call absorbs it — on the first validation failure
  it appends a "reply with only valid JSON" nudge to the prompt and escalates to the
  backup Groq key, then the fallback model, before exhausting remaining primary retries.
  generate_spec delegates to raw codegen if exhausted.

## Layout + explanation quality pass (Aug 26, 2026)
Research grounding: Manimator (arXiv 2507.14306) — "Element Layout" is its own quality
axis, improved by explicit layout planning; PhysicsSolutionAgent (2601.13453) — planner
emits explicit per-scene layout; LLM2Manim (2604.05266) — Mayer's principles
(segmenting / signaling / weeding).
Compiler fixes (positions now deterministic, not LLM's problem):
- Regions are boxes with a 3x3 slot grid; repeated placements auto-spread instead of stacking.
- link() helper picks facing edges from actual positions — no more backwards arrows.
- Labels default away from the nearest frame edge.
- Prompt rules: multi-item diagrams use explicit at-coordinates >=2.2 apart; one focal point/beat.
Prompt upgrades (explanation quality):
- spec_coder: segmenting (one idea per beat), signaling (highlight key object per beat),
  weeding (remove stale objects), hook->mechanism->formalize->takeaway arc.
- director: narration must explain WHY/HOW with signposts; visual_description must state
  spatial composition ("X left, Y right"), not just list objects.

## Frame clamping + vision critic (Aug 26, 2026)
- Left-cutoff root cause: LLM `at` coords and slot math could exceed the 7.11-unit
  half-frame. Compiler now clamps every position into a safe content band, with
  per-op margins (shape radius+label room for shapes; length-estimated half-width
  for text/equations). Verified with worst-case off-screen spec.
- Vision critic wired into scene graph (render -> merge/captions -> critique -> fix/accept),
  reviews the exact delivered candidate and permits one reviewed repair. Cost-controlled:
  <=3 frames @480px JPEG q60 (~500 img tokens total).
- This Groq account currently has NO vision model (llama-4-scout absent;
  groq/compound rejects image content arrays). Critic auto-disables on
  model_not_found and re-enables by restart once a vision model exists.

## Cross-scene context fix (Aug 26, 2026)
Symptom: scene 1 acceptable, later scenes incoherent.
Root cause: every scene generated independently — spec generator saw only its own
narration + thin visual_description. AnimG comparison: they sidestep this entirely
(one concept per video, Claude Sonnet, human approves spec pre-render).
Fixes:
- Sequential production (ANIMIND_SEQUENTIAL_SCENES=true, default): each finished
  scene's SceneSpec JSON (truncated to 1500 chars) rolls forward as context for the
  next generation, with continuity rules (same color/shape for same concept,
  re-introduce recurring motifs, don't repeat visuals, end clean).
- Director prompt now requires a consistent visual language across scenes
  (fixed shape+color per core concept) written into visual_description.
- scenes.spec_json column added (migrated via ALTER TABLE) so specs persist for
  regeneration and context.

## Vision critic LIVE via AgentRouter (Aug 26, 2026)
- Provider: agentrouter.org (OpenAI-compatible), model claude-opus-4-8, key in
  backend/.env as ANIMIND_ROUTER_API_KEY (gitignored).
- Gotcha: AgentRouter whitelists client User-Agents; plain OpenAI SDK UA gets 401
  "unauthorized client". Fix: default_headers={"User-Agent": "opencode/1.0.0"}.
- Structured output NOT used (gateway/Claude may not honor response_format);
  prompt demands bare JSON, lenient brace-salvage parse. Fail-open preserved.
- Verified live: correctly REJECTED an old scene_final.mp4 that rendered a
  "Hello, World!" placeholder instead of the intended content — the exact
  failure class that previously shipped silently.
- Cost per critique: 3 frames @480px (~500 img tokens) + ~200 text tokens.

## Production integrity hardening (Aug 26, 2026)
- Root cause of false `ready`: Manim can exit 0 for empty code, while the renderer's
  fixed output glob found an MP4 from an earlier attempt. Each attempt now gets an
  isolated temp media directory and unique output name; empty/invalid/no-animation
  code fails before rendering, and stale stable output is removed first.
- Project publication now requires every storyboard scene to be `ready` with an
  existing video. Partial scene sets are never stitched as the canonical final.
- Rerun lifecycle clears stale error/final fields; failed runs cannot serve an old
  final video. Per-project locks reject overlapping produce/regenerate operations.
- Sequential context bug fixed: `run_scene` no longer overwrites its context input.
  Raw fallback/fixer prompts also receive prior-scene context; obsolete rejected specs
  are cleared. Regenerating scene N rebuilds N and all downstream scenes.
- TTS is now actually the scene-graph entry node; the previous graph registered it but
  entered at codegen, which made every scene muted and removed measured timing.
- Vision QA remains downscaled (3x480px q60) and is capped at two candidate reviews.
  A second rejection becomes a real scene failure instead of silently becoming ready.
- Compiler now auto-fits title/text/equations/axes to region boxes, clamps actual
  mobject bounds after placement, keeps labels out of the center gutter, and rejects
  underspecified title-only specs before a render call.
