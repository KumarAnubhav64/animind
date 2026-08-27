# AniMind — Project Plan

**AniMind** (Animation + Mind): a full-stack generative platform that turns any topic into a
3Blue1Brown-style animated explainer video — with an editable storyboard, renderer-in-the-loop
code generation, and AI voiceover. Powered end-to-end by the Groq API.

---

## 1. Product Vision

Teachers, EdTech teams and creators want animated explainers but can't write Manim.
AniMind generates a **narrated animated video from a single topic prompt**, and — unlike
one-shot generators — exposes an **editable storyboard** so humans stay in the loop:
edit narration, regenerate individual scenes, view/fix code, then export the final MP4.

### Target users (v1)
- Educators preparing visual explanations
- Content creators / YouTubers exploring topics
- EdTech content teams prototyping lessons

---

## 2. Architecture

```
┌───────────────────────────────────────────────────────────────┐
│ Frontend — Next.js 14 + Tailwind + shadcn/ui                  │
│  • New project page  (topic, audience level, subject)         │
│  • Storyboard editor (scene cards + timeline + statuses)      │
│  • Per-scene: narration edit · code viewer · regenerate       │
│  • Final player page (streamed MP4)                           │
└──────────────┬────────────────────────────────────────────────┘
               │ REST + SSE (live progress)
┌──────────────▼───────────────────────────────────────────────┐
│ Backend — FastAPI + SQLite + asyncio worker pool              │
│                                                               │
│  Orchestrator (LangGraph graphs, parallel per scene)          │
│   ┌─────────────────────────────────────────────┐             │
│   │ STUDIO GRAPH (storyboard)                   │             │
│   │  Writer → Director ⇄ Producer (feasibility  │             │
│   │  review, ≤2 revision loops)                 │             │
│   └──────────────────┬──────────────────────────┘             │
│   ┌──────────────────▼──────────────────────────┐             │
│   │ SceneWorker × N (parallel)                  │             │
│   │  tts ── (fail → muted+captions fallback)    │             │
│   │  generate_code ─┐                           │             │
│   │   render ◀ retry│ (RITL ≤5, Fixer agent)    │             │
│   │   merge (moviepy | captions)                │             │
│   └──────────────────┬──────────────────────────┘             │
│                      ▼                                        │
│              Stitcher → final_video.mp4                       │
└───────────────────────────────────────────────────────────────┘
```

### Why LangGraph?
The scene workflow is a natural state machine:
`generate_code → render_ok? → (fix_code ↺ | tts ∥) → merge`.
LangGraph models this with explicit state + conditional edges, gives us checkpointing of
scene state for free, and makes the v1.5 vision-feedback node a drop-in addition.
Model calls go through `langchain-groq` (`ChatGroq`) with structured output (Pydantic)
for the planner's JSON storyboard.

---

## 3. Pipeline Stages

| # | Stage | Tech | Notes |
|---|-------|------|-------|
| 1 | Storyboard planning | Groq chat model + `json_schema` structured output | Pedagogy-aware prompt; 3–4 scenes, ≤30s narration each |
| 2 | Scene codegen | Groq coding model | House-style system prompt + Manim cheat-sheet + few-shot |
| 3 | Render-in-the-loop (RITL) | `manim render -qm` subprocess | stderr fed back to Fixer prompt, max 5 retries |
| 4 | Voiceover | Groq PlayAI TTS (`playai-tts`) | WAV per scene; duration measured after synthesis |
| 5 | Audio/video merge | moviepy | Freeze last frame if audio longer than animation |
| 6 | Stitch | moviepy concatenate | Final MP4 at 720p30 |

## 4. Prompt Engineering (core IP)

Three system prompts in `backend/app/prompts/`:

1. **PlannerAgent** — pedagogy structure (hook → intuition → formalize → recap),
   one clear visual idea per scene, audience-level calibration,
   strict JSON schema via Pydantic (`Storyboard`, `Scene`).
2. **SceneCoder** — enforced *house style* (the "3B1B look"):
   - dark background `#1c1c1c`, fixed palette constants
   - font ≥ 28pt, frame margins, no overlapping objects
   - root class always `VideoScene`, no fade-out ending
   - assets must be created in-code (no external files)
   - **animation duration ≈ measured TTS audio duration** (injected at runtime)
   - curated inline Manim API cheat-sheet (beats full RAG per TEA ablations)
   - 2 few-shot examples
3. **Fixer** — previous code + truncated stderr, temperature lowered each retry.

## 5. Data Model (SQLite)

- `projects`: id, topic, audience_level, subject, status, final_video_path, created_at
- `scenes`: id, project_id, index, title, narration, manim_code, status
  (`pending|coding|rendering|tts|merging|ready|failed`), error, attempts,
  video_path, audio_path, duration_s

## 6. API

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/projects` | Create project + generate storyboard |
| GET | `/api/projects/{id}` | Project + scenes |
| POST | `/api/projects/{id}/produce` | Kick off scene production (async) |
| POST | `/api/scenes/{id}/regenerate` | Re-run one scene |
| PATCH | `/api/scenes/{id}` | Edit narration/title manually |
| GET | `/api/projects/{id}/events` | SSE progress stream |
| GET | `/api/videos/{project_id}` | Stream final MP4 |

## 7. Scope

### v1 (this prototype)
- Core pipeline end-to-end, storyboard editor, SSE progress, final MP4 export
- Cap: 4 scenes, ~60–90s videos

### Deferred (v1.5+ roadmap)
1. **Vision feedback loop** — screenshot start/mid/end frames → Llama-4 Scout (Groq vision) → layout fixes (biggest known quality lever; TEA shows human-made beats AI mainly on layout)
2. Full RAG over Manim docs (inline cheat-sheet first — research shows mixed RAG results)
3. Celery/Redis queue, GPU rendering
4. Auth, multi-user projects, sharing links
5. Style templates/themes, ElevenLabs voices, background music

## 8. Known Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Hallucinated Manim APIs / LaTeX errors | Cheat-sheet + few-shot + RITL retries |
| Bad element layout (top complaint in literature) | Strict layout rules in prompt; v1.5 vision loop; manual edit UI |
| Narration ≠ animation length | Measure TTS audio → inject duration constraint into codegen |
| Groq rate limits on parallel scenes | Worker pool capped at 3–4 concurrent scenes |
| Render latency (~30–90s/scene CPU) | Parallel workers, `-qm` quality, SSE keeps user informed |

## 9. Validation Plan

Run ≥10 topics across math / physics / CS / biology. Track:
render success rate, retry counts, wall-clock time, visual spot-check.
Target: >80% scenes render without manual intervention to justify product investment.

## 10. Repo Layout

```
animind/
├── PLAN.md                  ← this file
├── README.md
├── research/                downloaded arXiv papers (TEA, LLM2Manim, ManimTrainer)
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI routes (controller layer)
│   │   ├── config.py        env settings (pydantic-settings)
│   │   ├── schemas.py       API Pydantic models
│   │   ├── db/              model → session → repository layers
│   │   │   ├── models.py    SQLAlchemy ORM: Project, Scene
│   │   │   ├── session.py   engine/session factory
│   │   │   └── repositories.py  ProjectRepository, SceneRepository
│   │   ├── prompts/         planner.py, coder.py, fixer.py
│   │   ├── agents/          llm.py (ChatGroq factories), planner_agent.py,
│   │   │                    scene_graph.py (LangGraph RITL pipeline), tts.py (PlayAI)
│   │   ├── pipeline/        renderer.py (manim), video.py (moviepy merge/stitch),
│   │   │                    events.py (SSE pub/sub)
│   │   └── services/        storyboard_service.py, production_service.py
│   ├── pyproject.toml       uv-managed deps
│   └── .env.example
├── frontend/
│   └── (Next.js app)
└── media/                   generated artifacts (gitignored)
```

### Layering rule (keeps navigation easy)
`main.py (routes) → services/ (business logic) → db/repositories.py (all SQL) → db/models.py (ORM)`
