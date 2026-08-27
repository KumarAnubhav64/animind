# AniMind — Project Status & Work Log

> **What it is:** AI-generated animated explainer videos. Enter a topic → get a
> 3Blue1Brown-style narrated animation with an editable storyboard. Full-stack
> prototype powered by the Groq API (LangGraph + ChatGroq + Manim CE).

**Repos:** `backend/` (FastAPI, branch `master`) · `frontend/` (Next.js 14, branch `main`)

---

## 1. Architecture

A multi-agent "animation studio" pipeline (LangGraph):

```
                    STUDIO (storyboard)
  Writer (script outline) → Director (visual storyboard)
        ⇅  Producer (feasibility review, ≤2 revision loops)

                    PRODUCTION (per scene, sequential by default)
  TTS voiceover ──┐ (on failure → muted scene with burned-in subtitles)
  SpecCoder → deterministic compiler → manim render
        ⇅  raw-code/Fixer fallback (renderer-in-the-loop, ≤5 retries)
  moviepy merge → vision QA (3 downscaled frames) → stitch → final_video.mp4
```

### Backend layout (`backend/app/`)
| Path | Purpose |
|---|---|
| `main.py` | FastAPI routes (controller layer) |
| `services/storyboard_service.py`, `production_service.py` | Business logic |
| `db/` | SQLAlchemy models → repositories (all SQL) |
| `agents/` | `studio_graph` (Writer⇄Director⇄Producer), `scene_graph` (TTS→spec/codegen→render→merge→vision QA), `tts.py`, `llm.py`, `math_expert.py`, `planner_agent.py`, `vision_critic.py` |
| `prompts/` | The core IP: `writer`, `director`, `producer`, `coder` (raw Manim), `spec_coder` (declarative spec), `fixer` |
| `pipeline/` | `spec_compiler` (spec→Manim), `renderer` (manim), `video` (moviepy), `frames` (vision frames), `events` (SSE bus), `telemetry` |
| `schemas/spec.py` | Declarative `SceneSpec` / `SpecAction` model |

### Two codegen paths (the "spec" pipeline is preferred)
1. **Spec path:** `SpecCoder` LLM emits a declarative `SceneSpec` (spatial blueprint + beats + actions) → the **deterministic compiler** turns it into Manim. Guarantees: no API hallucinations, no layout collisions, house style enforced, consistent timing.
2. **Raw-code fallback:** `Coder` LLM writes Manim directly; `Fixer` feeds renderer errors back (≤5 retries).

### Key deterministic protections in the compiler
- Region system (`REGIONS`) — named boxes (`center/left/right/top/bottom/...`) the LLM places content into.
- Slot grid + overlap detection — objects are nudged to a collision-free position.
- `_fit()` + `_keep_in_frame()` — sizes to region and clamps to frame `[-6.75,6.75]×[-3.5,2.1]`.
- Whitelisted Manim API + shape constructor table — the LLM never writes raw Manim in spec mode.

### Frontend (`frontend/src/`)
- `app/page.tsx` — topic input.
- `app/project/[id]/` — storyboard editor + player (SSE live progress).
- `components/SceneCard.tsx`, `ChatHistory.tsx` — per-scene status/edit/regenerate, chat UI.
- `lib/` — `detectExpertLabel` (math/physics topic detection), streaming client.

### Data
- SQLite DB (`backend/animind.db`): projects, scenes, messages, telemetry.
- Render artifacts under `backend/media/<project_id>/`.

---

## 2. Work log — backend (committed)

| Commit | What |
|---|---|
| `bab84a2` | Math Expert gate, spatial layout planning, telemetry, schema fixes |
| `d614d4a` | Cross-scene visual continuity |
| `4c8a654` | Always run mathcheck + enrich continuity context + cap context length |
| `687ad96` | Persistent chat history |
| `cdb83a1` | Sanitize Unicode control chars in narration; fix final video display |
| `18b29a1` | TTS always used when enabled, no silent fallback |
| `934b8f8` | Speed up mathcheck — 30s timeout, 1 retry |
| `1c39810` | Use full-frame limits when actions have explicit `at:[x,y]` |
| `483291b` | Show previous projects in sidebar + list projects endpoint |
| `a18f52d` | TTS rate-limit falls back to subtitles, other errors raise |
| `eae8257` | 3D shapes for physics/geometry (Sphere, Cube, Cylinder, Cone, Torus) |
| `96ffd82` | Pre-made SVG asset library (apple, car, earth, gear, …) |
| `7ac8c5d` | Enforce `add_asset` for real-world objects in SpecCoder prompt |
| `c5d41e3` | Stronger prompt rules for assets and math rendering |
| `7b12dc9` | Overlap-avoidance + phased timeline in director/speccoder prompts |
| `afc2da7` | Few-shot examples + spatial precision rules for SpecCoder |
| `5bdfdf7` | Stream granular specgen progress events with beat counts |
| `c68e959` | Rotate to backup Groq API key after primary-key retries exhausted |

## 3. Work log — frontend (committed)

| Commit | What |
|---|---|
| `6302ddd` | `detectExpertLabel` matches Fourier/transform/wave/spectrum for math topics |
| `3e58672` | `detectExpertLabel` also matches Laplace/transform keywords |
| `7ec9715` | Show live elapsed time on running agent step (doesn't look stuck) |

## 4. Current uncommitted work — "output quality" (in progress)

Root problem reported by user: **generated scenes look bad — scaling is wrong and there
is no motion design** (not close to 3Blue1Brown).

### 4a. Scaling fix (done, verified)
- **`spec_compiler.py`** — `_fit()` was shrink-only: a `Circle(radius=0.9)` placed in a region stayed tiny.
  - `_fit` now supports `fill=True` → region-placed shapes/assets **grow to fill their region**.
  - Explicit `at:[x,y]` keeps author's intended size; dots stay small (markers).
  - Overlap detection (`_bbox_half_extents`) uses the grown footprint.
- **`prompts/spec_coder.py`** — added a SCALING rules section + fixed the "GOOD" few-shot
  (hero unit circle now placed in a region *without* `at`/`scale` so it auto-grows).
- **`prompts/coder.py`** (raw fallback) — added frame-size scaling guidance.
- **Verified:** `44/44` tests pass; test render of a unit-circle scene: circle grew from
  nearly invisible to **313 px filling its left region**.

### 4b. Motion design (in progress)
- **`schemas/spec.py`** — added `turns` field to `SpecAction`.
- **`spec_compiler.py`** — new motion ops so the deterministic path emits *movement*:
  - `rotate {id, turns, seconds?}` → `self.play(Rotate(..., angle=TAU*turns), rate_func=linear)`
  - `pulse {target}` → quick scale up/down attention highlight
  - `move {id, ..., seconds?}` → now honors a custom duration
- **`prompts/spec_coder.py`** — new MOTION DESIGN rules + `rotate`/`pulse` ops + a
  "spinning phasor" GOOD/BAD example.
- **`prompts/coder.py`** — added MOTION DESIGN rules + two **3B1B-style motion few-shots**
  (faithful adaptations of the MIT-licensed Manim CE gallery patterns):
  1. Rotating radius + dot tracing a sine curve (`SineCurveUnitCircle` style).
  2. Sum of rotating vectors (phasors head-to-tail, `ValueTracker` + `always_redraw`).
- **Remaining:** finish the raw-coder motion few-shots (currently mid-edit), render a
  motion example to verify, run full test suite, commit.

---

## 5. Current state & known issues

### Server
- Running via nohup → `/tmp/animind.log`, uvicorn **`--reload-dir app`** (important: the full
  `--reload` used to watch `media/`, restarting the server on every scene write and killing
  in-flight production tasks — the cause of the original "stuck at 937s/8140s" bug).

### Verified end-to-end
- Project `17cde613f63e` ("What is 2+2 in math") produced fully → `final_video.mp4`
  (635 K, 78.8s). Backup Groq key rotation confirmed working.

### Zombie projects in DB (from before the reload fix)
- Tasks died when the server restarted; DB rows left `producing`, will never progress on
  their own: `cdc02f7c9571`, `e1d3227ca339`, `187ce5d44885`, `0550d26e304f`
  (scene 0 = `tts`, rest `pending`). `2dd4a8fa07d0` = failed.
- Ready/finished: `17cde613f63e`, `6c2d16895515`, `3244c713d5e4`.

### Known quirks
- **Race:** producing immediately after project creation can run before the async storyboard
  writes scenes → `restitch` raises "Cannot publish final video until every scene is ready".
  Candidate for a guard in `produce_project`.
- **Vision critique:** primary router vision model is quota'd out (403) as of 2026-08-27;
  wired `ANIMIND_VISION_MODEL_FALLBACK=qwen/qwen3.8-27b` so QA keeps running. If the quota
  is restored, the primary re-enables automatically after an hour. Verify with
  `uv run python scripts/check_models.py`.
- **Rate limits:** Groq is heavily rate-limited (429s, daily token caps); backup key in
  `backend/.env` (`ANIMIND_GROQ_API_KEY_BACKUP`).
- **Custom layout region names** (e.g. `"circle_area"`) don't exist in the compiler's
  `REGIONS` dict — placement falls back to `center`. Use `left/right/center/...` names.

---

## 6. Next steps

1. Finish raw-coder motion few-shots; render a motion example to verify; full `pytest`; commit.
2. Fix the custom-layout-region fallback (`REGIONS` lookup) if custom region names matter.
3. Guard `produce_project` against produce-before-storyboard race.
4. Clean up / re-produce the zombie Fourier projects.
5. Per-scene quality score (frame-diff heuristic) as an auto-retry signal (v1.5 roadmap).

## 7. Reference docs
- `README.md` — how to run, stack table.
- `PLAN.md` — architecture & roadmap.
- `QUALITY_NOTES.md` — tracked video-quality findings per iteration.
- `backend/QUALITY_NOTES.md` — backend-side quality notes.
- `research/` — arXiv papers this design draws on.
