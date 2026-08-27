# AniMind — How Everything Works

A deep dive into the system: the full flow, every agent, the two codegen paths,
the quality gates, and how the pieces fit together. File paths are relative to `backend/`.

---

## 1. Big picture

**Input:** a topic (e.g. "How does a Fourier transform work?"), an audience level, optional subject.
**Output:** a complete narrated, 3Blue1Brown-style explainer video (`final_video.mp4`) made of
4+ scenes, each its own Manim animation with a TTS voiceover.

There are **two phases**:

1. **STUDIO** — planning. Three LLM agents (Writer → Director → Producer) turn the topic into an
   editable storyboard of scenes. No pixels are produced.
2. **PRODUCTION** — making. For each scene: TTS voiceover → generate Manim code → render →
   merge audio/video → visual QA → stitch everything into one MP4.

Both phases are **async**: the API returns immediately and streams live progress to the
frontend over **SSE** (Server-Sent Events).

```
Browser → FastAPI
   │  POST /api/projects            (persist project, status=drafting)
   │  asyncio.create_task(generate_storyboard)   ← runs in background
   │  GET /api/projects/{id}/events              ← SSE stream
   │
   ▼
STUDIO (app/agents/studio_graph.py)
   write → direct → review  (↺ revise up to max_storyboard_revisions=2)
   │
   ▼ persist Scene rows (title, narration, visual_description, status=pending)
   │
   │  POST /api/projects/{id}/produce   (or a chat message triggers it)
   ▼
PRODUCTION (app/services/production_service.py → app/agents/scene_graph.py)
   for each scene (sequential by default):
      TTS → specgen (or codegen) → mathcheck → render → merge → vision QA → accept
   │
   ▼
restitch → final_video.mp4 → project status=ready → SSE "ready"
```

---

## 2. End-to-end walkthrough (line by line)

### Step 1 — Create a project
`POST /api/projects` → `app/main.py:67`
1. Rejects if `ANIMIND_GROQ_API_KEY` is not set (503).
2. `persist_project(...)` (`app/services/storyboard_service.py:17`) writes a `Project` row
   with `status="drafting"` **immediately**, so the UI can subscribe to SSE before any LLM runs.
3. `asyncio.create_task(generate_storyboard(project.id))` kicks off the studio in the background.
4. Returns the project JSON (with empty scenes).

### Step 2 — Studio planning (background)
`generate_storyboard` (`storyboard_service.py:27`) → `run_studio` (`agents/studio_graph.py:199`)
runs a LangGraph `StateGraph`:

```
entry → write → direct → review ──approved→ END
                          │
                          └─issues→ revise → direct → review …  (max 2 revisions)
```

- **Writer** (`write_node`) → `ScriptOutline` (structured JSON) via `planner_llm()`.
  Produces key teaching ideas, ordered intuition→formalism.
- **Director** (`direct_node`) → `Storyboard` (structured JSON) via `planner_llm()`.
  Maps the outline to `Scene`s, each with `title`, `narration`, `visual_description`
  (concrete, renderable visual intent). On revision, gets a `director_revision_prompt`
  listing the Producer's issues.
- **Producer** (`review_node`) → `FeasibilityReport` `{approved, issues}`. Rejects
  storyboards that can't render (vague visuals, too long, etc.).
- All structured LLM calls go through `structured_call(...)` (`studio_graph.py:32`):
  3 attempts, Groq `json_schema` method (tool-calls fail on nested schemas), with
  **backup Groq key + fallback model** handling for daily-cap errors.
- Each scene is persisted (`scene_repo.create`, status=`pending`) and an assistant chat
  message lists the planned scenes. Storyboard failure → project `failed`.

### Step 3 — Produce (kicked off by button or chat message)
`POST /api/projects/{id}/produce` or `POST .../messages` → `production_service.produce_project`
(`production_service.py:339`):

1. Guards against double-production (`_active_projects` set, 409 if already running).
2. Sets project `status="producing"`, deletes any old final video.
3. Resets all scenes to `pending`.
4. **Sequential mode** (`sequential_scenes=true`): `_produce_sequential`
   (`production_service.py:198`) produces scenes in order, **carrying each delivered
   scene's "continuity context" forward** so scene N+1 knows what scene N left on screen.
   If any scene fails, production stops (no wasted free-tier calls).
5. `restitch` (`production_service.py:442`): verifies every scene is ready + has a real
   video file, then concatenates scene MP4s into `media/<project>/final_video.mp4`.
6. Streams `{"type":"project","status":...}` through `ready` or `failed`.

### Step 4 — Per-scene production (the scene graph)
`produce_scene` (`production_service.py:227`) → `run_scene` (`agents/scene_graph.py:588`)
runs the per-scene LangGraph:

```
entry
 ├─ TTS enabled → tts ──→ specgen (if codegen_mode=spec) ──→ mathcheck ──→ render
 │                        └──┴─ spec fails → fallback_codegen ──→ render
 └─ TTS disabled→ specgen ─────────────────────────────────────→ render
                                                      │
                                          render fails?
                                          │ attempts<max → fix (if spec) / fix
                                          │ else         → fail
                                          ▼
                                        merge ──→ critique ──→ accept (ready)
                                          │ fail      │       │
                                          │           └─issues→ fix (re-render)
                                          ▼
                                         fail
```

Nodes (each streams a `workflow` SSE event with the agent name + message):

| Node | Agent label | What it does |
|---|---|---|
| `tts` | Voice Artist | `synth_tts` — Groq PlayAI TTS → `audio.wav`, measures duration. 429 → **muted + captions** fallback. |
| `specgen` | SpecCoder | `generate_spec` — declarative `SceneSpec` → deterministic compiler → Manim code (Tier 1). Failure → falls to raw codegen. |
| `mathcheck` | Math Expert | `mathcheck` — deterministic checks + optional LLM review of the spec before compiling (fail-open). |
| `codegen` | SceneCoder | `generate_code` — raw LLM Manim (Tier 2, also the fallback). |
| `fix` | Fixer | `fix_code` — feeds render/QA errors back to the Fixer LLM (temperature drops each retry). |
| `render` | Renderer | `render_manim` — writes `scene.py`, runs `manim render`, returns video path or error. |
| `merge` | Editor | audio+video merge (holds last frame if narration is longer), or burned-in captions. |
| `critique` | Vision Critic | screenshot-based visual QA on start/mid/end frames. |
| `accept` / `fail` | Producer | terminal nodes → scene `ready` / `failed`. |

---

## 3. The two codegen paths

This is the heart of the system. Both paths produce the same thing (Manim `VideoScene`),
but through completely different mechanisms.

### Tier 1 — Declarative spec → deterministic compiler (preferred)
`codegen_mode="spec"`, nodes `specgen` + `mathcheck`.

1. **SpecCoder LLM** (`prompts/spec_coder.py`) reads narration + visual intent and returns a
   **`SceneSpec` JSON** (schema in `app/schemas/spec.py`):
   - `layout.regions` — a spatial blueprint (named regions like `left_area`, `eq_area`).
   - `beats[]` — 4–8 narration thoughts, each with `actions[]`.
   - `SpecAction` ops: `set_title, add_text, add_equation, add_shape, add_asset, add_axes,
     add_bars, label, connect, animate, transform, move, rotate, pulse, remove, wait`.
   - The LLM is **never allowed to write Manim**. It only declares intent.
2. **Deterministic compiler** (`pipeline/spec_compiler.py`) turns that JSON into Manim:
   - `REGIONS` table — named boxes (`center/left/right/top/bottom/...`), each a
     `(cx, cy, half_w, half_h)`.
   - `_fit_and_place` — sizes each object to its region (heroes **grow to fill** via
     `_fit(..., fill=True)`; explicit `at:[x,y]` keeps author size; dots stay small) and
     `_keep_in_frame` clamps to `[-6.75,6.75]×[-3.5,2.1]`.
   - Slot grid + AABB overlap detection (`_slot_position`, `_find_free_position`) — objects
     are nudged to a collision-free spot instead of stacking.
   - Whitelisted shape constructors (`Circle`, `Square`, `Dot`, 3D shapes via
     `ThreeDScene`...). Only `from manim import *` + helpers (`_fit`, `_keep_in_frame`, `link`)
     are emitted.
   - Timing: each `emit()` accumulates `duration`; if the scene runs shorter than the
     narration audio, a final `self.wait(...)` holds the last frame.
3. **Math Expert** (`agents/math_expert.py`) runs **before** compilation:
   - Tier 1 deterministic: valid ops/colors/shapes, LaTeX brace balance, plot-expr syntax
     and undefined names, finite numbers, valid ranges, positive scale/seconds.
   - Tier 2 optional LLM: reviews formulas/numbers/ranges against the narration, returns
     **surgical per-action fixes** (`{id, field, value}`) applied deterministically, then
     recompiles. **Fail-open** — never blocks the pipeline on budget.
4. If the spec path fails *or* the compiled scene fails to render, the graph takes
   **`fallback_codegen`** → raw LLM codegen.

**Why two tiers:** the spec path trades visual freedom for reliability — no hallucinated
APIs, no layout collisions, no broken syntax — at the cost of less cinematic motion.
The raw path (Tier 2) can do anything Manim can do (updaters, `always_redraw`,
`TransformMatchingTex`...) but risks invalid code. The current quality work is about
(1) making the spec path scale/move well and (2) teaching the raw path motion via
3B1B-style few-shots.

### Tier 2 — Raw LLM codegen + renderer-in-the-loop
Nodes `codegen` / `fix` / `render`.

1. **SceneCoder** (`prompts/coder.py`) writes full Manim `VideoScene.construct()` from the
   narration + a HOUSE_STYLE + MANIM_CHEATSHEET + few-shot examples (including the new
   motion-design patterns).
2. `normalize_manim_code` applies compatibility fixes
   (`set_start_and_end_points`→`put_start_and_end_on`, `UP.rotate`→`rotate_vector`, ...).
3. `render_manim` (`pipeline/renderer.py`):
   - Writes `scene.py`, parses it with `ast` to pre-validate (must define `VideoScene`,
     must have a `construct` that plays/adds something).
   - `preflight_visual_code` rejects known garbage (Hello-World placeholders, shape-only
     transforms).
   - Runs `manim render -qm` in an isolated media dir with a 300s timeout.
4. **Fixer loop:** if render fails, `fix_code` sends the error back to the Fixer LLM
   (temperature `max(0, 0.4 - 0.1*attempt)` — explores early, exploits late) up to
   `max_scene_retries=5`. A fixed candidate that still fails preflight triggers a fresh
   full codegen.

---

## 4. Audio, merge, and captions

- **TTS** (`agents/tts.py`): Groq `canopylabs/orpheus-v1-english`, voice `autumn`, WAV.
  On 429/rate-limit → **muted scene** with burned-in subtitles (narration split into
  ≤6-word chunks, timed at ~2.6 words/sec, rendered via PIL and overlaid by moviepy).
- **Merge** (`pipeline/video.py:128`): `merge_audio_video` — if narration is longer than the
  animation, the **last frame is frozen** for the remainder so the video never outpaces
  speech. Else trims to audio length.
- **Stitch** (`video.py:161`): `concatenate_videoclips` with `method="compose"`, resized to a
  uniform frame size, written with libx264+aac.
- A **merge failure** ships the raw animation rather than losing the scene (last resort).

---

## 5. Quality gates

### Vision Critic (`agents/vision_critic.py`)
- Extracts 3 downscaled frames (start / middle / end) via `extract_frames`.
- Sends them as images + narration + director's intent to a vision LLM.
- **Fallback chain:** primary `vision_model` (`claude-opus-4-8` via AgentRouter) →
  `vision_model_fallback` (a Groq vision model, e.g. `qwen/qwen3.8-27b`) → fail-open.
  A quota/403 error disables the primary for 1 hour before retrying; a missing model
  disables it for the process. The fallback keeps visual QA running when the router
  account is out of quota.
- Verdict `{passed, issues, skipped_reason}` on: overlap, off-screen, layout balance, relevance.
- Not passed → `fix` (re-render with feedback) up to `vision_max_attempts=2`, then fail.
- **Fail-open** (always counts as passed on any error, but records a `skipped_reason`
  that is logged, streamed as a workflow `qa_warning`, and surfaced in
  `_workflow_message` — so a dead vision model is loud, never silent).
- Health-check both paths with `uv run python scripts/check_models.py`.

### Continuity (`production_service.py:69-175`)
- Each finished scene's spec is summarized into a human-readable inventory
  (`_extract_visual_state`: objects alive at the end, their color/position/text).
- The next scene's coder receives this as `context` so it re-introduces the same shapes
  and keeps colors consistent across scenes. Capped at ~3000 chars.

### Deterministic preflight
- `ast` validation of the generated Manim code before it ever reaches Manim.
- `preflight_visual_code` placeholder/shape-stack rejection.

---

## 6. Resilience & rate-limit handling

Free-tier Groq is TPM/daily-cap constrained. Defense in depth:

1. **SDK backoff:** `max_retries=6, timeout=120` on every ChatGroq.
2. **`llm_with_retry`** (`scene_graph.py:30`): 4 attempts; on 429 sleeps 30s; detects
   `tokens per day` / `tpd` and switches to the **backup Groq key** (`_backup_groq`),
   then to a **fallback model** (`qwen/qwen3.8-27b`).
3. **Sequential scenes** (`sequential_scenes=true`): one scene at a time instead of a burst,
   rolling context forward. Parallel option exists (max 2) but quality > speed.
4. **Fail-open gates:** Math Expert and Vision Critic never deadlock the pipeline.
5. **Degradation chain:** TTS down → captions; merge down → raw video; codegen down → spec
   path only, etc.

---

## 7. Data model (`app/db/models.py`)

- **Project** — topic, audience_level, subject, status (`drafting/producing/stitching/
  ready/failed`), error, final_video_path.
- **Scene** — project_id, idx, title, narration, visual_description, manim_code, spec_json,
  status, error, attempts, video_path, audio_path, duration_s.
- **Message** — chat history (role, content, optional video_path for the completion message).
- Repository layer (`app/db/repositories.py`) owns all SQL; services call repos, never SQLAlchemy directly.

Project/scene lifecycle statuses:
```
drafting → producing → stitching → ready
    │                      │
    └────────→ failed      └────────→ failed
```

---

## 8. Frontend flow (`frontend/src/`)

- `app/page.tsx` — topic form. Submits, gets a project id.
- `app/project/[id]/` — main page: subscribes to
  `GET /api/projects/{id}/events` (SSE) and renders live `workflow`/`scene`/`project`
  events with an **elapsed-time timer** on the current step.
- `SceneCard.tsx` — per-scene status card: shows status, attempts, error, "edit narration",
  "regenerate". Scene videos stream from `/api/scenes/{id}/video`.
- `ChatHistory.tsx` — chat side panel; sending a message triggers production
  (`POST /api/projects/{id}/messages`).
- `lib/detectExpertLabel.ts` — routes math/physics keywords (Fourier, transform, wave,
  spectrum, Laplace...) to the math "expert" treatment.
- On the final `project ready` SSE event, the player loads `final_video.mp4`.

---

## 9. Configuration (`app/config.py` + `.env`, prefix `ANIMIND_`)

| Setting | Default | Meaning |
|---|---|---|
| `groq_api_key`, `groq_api_key_backup` | "" | primary + backup keys |
| `planner_model` | `openai/gpt-oss-120b` | studio agents (only one that handles nested json_schema) |
| `coder_model` | `openai/gpt-oss-120b` | spec + raw codegen |
| `fixer_model` | `openai/gpt-oss-20b` | cheap repair LLM |
| `fallback_model` | `qwen/qwen3.8-27b` | used when primary hits a daily cap |
| `codegen_mode` | `"spec"` | `spec` (declarative) or `raw` |
| `sequential_scenes` | true | roll context scene-to-scene |
| `tts_enabled` | true | PlayAI narration |
| `vision_critique` | true | screenshot QA |
| `vision_model_fallback` | unset (e.g. `qwen/qwen3.8-27b`) | Groq vision model used when the primary vision model is down |
| `max_scene_retries` | 5 | render/fix attempts |
| `max_scenes` | 4 | scenes per project |
| `media_dir` | `media` | render artifacts |

---

## 10. Common failure modes (and how the system reacts)

| Symptom | Cause | Behavior |
|---|---|---|
| Project stuck `producing` forever | Server restarted mid-run (old bug: uvicorn `--reload` watched `media/`; every scene write restarted the server and killed the in-flight task) | Fixed by running with `--reload-dir app`. Historical rows are zombies — DB thinks running, no task alive. Needs manual cleanup/resume. |
| "Cannot publish final video until every scene is ready" | `produce` fired before async storyboard wrote scenes (race) | `restitch` guard; earlier scenes stop production. Guarding `produce_project` is a pending improvement. |
| Scene muted with subtitles | TTS 429 | Graceful fallback (by design). |
| Scene fails render repeatedly | hallucinated Manim API / bad layout | Fixer loop → fresh codegen → eventually `fail`. |
| Vision QA keeps rejecting | overlap / off-screen | Fix loop re-renders with feedback, then fails. |
| Static, badly-scaled scenes | spec compiler shrink-only `_fit`; prompts lacked motion/scaling rules | **Fixed in current work** (heroes grow to fill region; `rotate`/`pulse` ops; 3B1B-style motion few-shots). |
