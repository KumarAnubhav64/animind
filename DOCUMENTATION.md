# Animind — Complete Documentation

> A beginner-friendly guide to everything in this codebase.

---

## Table of Contents

1. [What is Animind?](#what-is-animind)
2. [How it works (big picture)](#how-it-works-big-picture)
3. [The two pipelines](#the-two-pipelines)
4. [Pipeline 1: Studio (planning)](#pipeline-1-studio-planning)
5. [Pipeline 2: Scene (production)](#pipeline-2-scene-production)
6. [The spec system (SceneSpec)](#the-spec-system-scenespec)
7. [How context flows between scenes](#how-context-flows-between-scenes)
8. [Vision critique (visual QA)](#vision-critique-visual-qa)
9. [Mayer's teaching principles](#mayers-teaching-principles)
10. [Treatment markdown](#treatment-markdown)
11. [How agents talk to each other (SSE events)](#how-agents-talk-to-each-other-sse-events)
12. [Key files and what they do](#key-files-and-what-they-do)
13. [How to run it](#how-to-run-it)
14. [Glossary](#glossary)

---

## What is Animind?

Animind is an **AI video generator**. You give it a topic (e.g. "How does photosynthesis work?") and it produces a **3Blue1Brown-style educational animation** — the kind with dark backgrounds, smooth geometric motion, and narrated explanations.

It does this by chaining together multiple AI agents, each with a specific job, in a pipeline. No human writes the animation code — the AI does everything from planning the script to rendering the final video.

---

## How it works (big picture)

```
You type a topic
       │
       ▼
┌──────────────────────────────────────────┐
│           STUDIO PIPELINE                │
│  Writer → Director → Producer            │
│  (plans the video)                       │
└──────────────────────────────────────────┘
       │
       │  produces 3-4 scenes, each with:
       │  title, narration, visual_description
       ▼
┌──────────────────────────────────────────┐
│          SCENE PIPELINE (× N scenes)     │
│  TTS → Spec → MathCheck → Render →       │
│  Merge → Critique → Accept               │
│  (builds each animation)                 │
└──────────────────────────────────────────┘
       │
       │  each scene produces a .mp4 video
       ▼
┌──────────────────────────────────────────┐
│           STITCHING                      │
│  all scene videos → final video          │
└──────────────────────────────────────────┘
       │
       ▼
   You get a final explainer video
```

---

## The two pipelines

### Pipeline 1: Studio (planning)

This is the **brain** of the system. Three AI agents collaborate to plan what the video will teach and how.

| Agent | Job | Input | Output |
|-------|-----|-------|--------|
| **Writer** | Structures the explanation | topic + audience level | outline with key ideas |
| **Director** | Storyboards it into scenes | outline | scenes with narration + visual plan |
| **Producer** | Reviews feasibility | storyboard | approve or reject (max 2 revisions) |

After approval, the scenes are saved to the database and production begins.

### Pipeline 2: Scene (production)

Each scene goes through its own pipeline. This is the **hands** — it actually builds the animation.

| Node | Job | What happens |
|------|-----|-------------|
| **TTS** | Generate voice narration | Narration text → audio file + duration |
| **Spec** | Plan the visual beats | Narration → SceneSpec JSON (declarative visual plan) |
| **MathCheck** | Verify math correctness | Checks formulas, axis ranges against narration |
| **Code** | Write Manim code | (only if spec fails) Raw LLM writes Python directly |
| **Render** | Render the animation | Runs Manim to produce a video clip |
| **Merge** | Combine audio + video | Narration audio + rendered video → merged clip |
| **Critique** | Visual QA | Screenshots checked for quality, relevance, correctness |
| **Accept** | Store the scene | If critique passes, the scene is marked "ready" |
| **Fix** | Repair issues | If critique fails, feedback is sent back to re-render |

---

## Pipeline 1: Studio (planning)

### Writer Agent

**File:** `backend/app/prompts/writer.py`

The Writer receives a topic and audience level, and produces an outline:

```json
{
  "working_title": "How Photosynthesis Works",
  "logline": "Plants convert sunlight into food using a two-stage process",
  "key_ideas": [
    "Chlorophyll absorbs light energy",
    "Light reactions split water molecules",
    "Calvin cycle builds sugar from CO2",
    "The whole process converts light → chemical energy"
  ],
  "misconception": "Plants get their mass from soil",
  "target_duration_seconds": 80
}
```

The Writer follows **Mayer's multimedia learning principles** (see below) — it hooks first, goes concrete before abstract, and builds one idea per scene.

### Director Agent

**File:** `backend/app/prompts/director.py`

The Director takes the Writer's outline and creates a **shot-by-shot storyboard** — 3-4 scenes, each with:

- **title** — short scene name
- **narration** — spoken prose (50-90 words, ~20-35 seconds)
- **visual_description** — phased sequence of what to show, with positions

The Director follows strict rules:
- Every object gets a position ("left", "right", "center")
- Visuals are phased (Phase 1, Phase 2, etc.)
- Consistent colors across scenes (blue circle stays blue)
- On-screen text is minimal — narration carries the explanation

### Producer Agent

**File:** `backend/app/prompts/producer.py`

The Producer reviews the storyboard for feasibility:
- Are scenes too complex for Manim?
- Are there math errors?
- Is the pacing right?

If rejected, the Director revises (max 2 times).

---

## Pipeline 2: Scene (production)

**File:** `backend/app/agents/scene_graph.py`

This is a **LangGraph state machine** — a directed graph where each node is a function that receives the current state and returns updates.

### The state

Every scene has a `SceneState` dict that flows through the pipeline:

```python
{
    "project_id": "abc123",
    "scene_id": "def456",
    "scene_idx": 0,
    "title": "Unit Circle and Sine Wave",
    "narration": "A point travels around...",
    "visual_description": "Phase 1: circle on left...",
    "context": "Scene 1 visual state: circle at (-3.4, 0)...",
    "project_topic": "How sine waves work",
    "audio_path": "/path/to/audio.wav",
    "audio_duration": 28.5,
    "code": "from manim import *...",
    "spec_json": "{\"title\": ..., \"beats\": [...]}",
    "treatment_md": "# Unit Circle\n\n## Overview\n...",
    "video_path": "/path/to/rendered.mp4",
    "status": "ready",
    "attempts": 2,
    "error": null,
}
```

Each node reads from this state and writes updates back to it.

### The graph

```
tts → specgen → mathcheck → render ──→ merge → critique → accept
                       │                   ↑         │
                       │                   │         ↓
                       └── codegen ────────┘     fix ─┘
                               │
                               └── fallback_codegen ──→ render
```

- **specgen** tries the declarative spec path (preferred)
- If specgen fails, it falls back to **codegen** (raw LLM writes Manim code)
- **mathcheck** only runs on the spec path (verifies formulas)
- **render** can fail → **fix** tries to repair the code → re-render
- **critique** screenshots the video and checks quality → **accept** or **fix**

---

## The spec system (SceneSpec)

**Files:**
- `backend/app/schemas/spec.py` — data model
- `backend/app/prompts/spec_coder.py` — prompt
- `backend/app/pipeline/spec_compiler.py` — deterministic compiler

This is the most important innovation in the codebase. Instead of asking the LLM to write Manim code directly (which often produces broken code), we ask it to write a **declarative SceneSpec** — a JSON blueprint — and then **compile** it deterministically into Manim code.

### What is a SceneSpec?

```json
{
  "title": "Unit Circle and Sine Wave",
  "layout": {
    "regions": [
      {"name": "circle_area", "area": "left", "at": [-3.4, 0]},
      {"name": "wave_area", "area": "right", "at": [3.4, 0]}
    ]
  },
  "beats": [
    {
      "description": "Show the unit circle on the left",
      "actions": [
        {"op": "set_title", "text": "Unit Circle"},
        {"op": "add_shape", "id": "circle", "shape": "circle", "color": "blue", "region": "circle_area"},
        {"op": "add_axes", "id": "axes", "x_range": [-1.5, 1.5, 0.5], "y_range": [-1.5, 1.5, 0.5], "at": [-3.4, 0]}
      ]
    },
    {
      "description": "Draw axes on the right for the sine wave",
      "actions": [
        {"op": "add_axes", "id": "wave_axes", "x_range": [0, 6.5, 1.57], "y_range": [-1.5, 1.5, 0.5], "at": [3.4, 0]}
      ]
    },
    {
      "description": "A dot orbits the circle, tracing the sine wave",
      "actions": [
        {"op": "add_shape", "id": "dot", "shape": "dot", "color": "yellow", "at": [-2.4, 0], "scale": 1.5},
        {"op": "rotate", "id": "dot", "turns": 2, "seconds": 4}
      ]
    }
  ]
}
```

### Available ops (what the spec can describe)

| Op | What it does | Key fields |
|----|-------------|------------|
| `set_title` | Scene title at top | `text` |
| `add_shape` | Add a geometric shape | `id`, `shape` (circle/square/dot/...), `color`, `region` or `at` |
| `add_asset` | Add a real-world object | `id`, `asset` (apple/car/earth/...), `color`, `region` or `at` |
| `add_equation` | Add a LaTeX formula | `id`, `tex`, `color`, `region` or `at` |
| `add_axes` | Add a coordinate system | `id`, `x_range`, `y_range`, `expr`, `region` or `at` |
| `add_bars` | Add a bar chart | `id`, `values`, `region` or `at` |
| `add_text` | Add a plain text label | `id`, `text`, `color`, `region` or `at` |
| `label` | Attach a label to an object | `id`, `text`, `target`, `direction` |
| `connect` | Draw a line between objects | `id`, `from`, `to`, `color` |
| `animate` | Trigger an animation | `target`, `anim` (write/fade_in/create/indicate/...) |
| `transform` | Morph one object into another | `id`, `tex` or `text` |
| `move` | Reposition an object | `id`, `region` or `at`, `seconds` |
| `rotate` | Spin an object | `id`, `turns`, `seconds` |
| `pulse` | Quick scale up/down | `target` |
| `remove` | Remove an object | `target` (or "all") |
| `wait` | Pause | `seconds` |

### Why this is better than raw codegen

1. **Deterministic** — the compiler always produces valid Manim code from a valid spec
2. **Retryable** — if the spec has issues, we can validate and retry (see below)
3. **Readable** — humans can read the spec JSON and understand what the animation will do
4. **Treatment markdown** — we can auto-generate a human-readable treatment from the spec

### Spec validation

**File:** `backend/app/schemas/spec.py` → `SceneSpec.validate_ids()`

After the LLM generates a spec, we validate it:
- Every `add_*` op must have an `id`
- Every `connect` must reference existing ids in `from` and `to`
- Every `animate`/`rotate`/`move`/`remove` must reference an existing id

If validation fails, the issues are fed back to the LLM and it regenerates (up to 2 retries).

### Spec compilation

**File:** `backend/app/pipeline/spec_compiler.py`

The compiler translates the declarative spec into imperative Manim code:
- `add_shape` → `Circle(color=BLUE).move_to(...)`
- `add_axes` → `Axes(x_range=[...], y_range=[...])`
- `rotate` → `self.play(Rotate(obj, angle), run_time=...)`
- `connect` → `Line(start, end, color=...)`
- etc.

The compiler handles:
- Position calculation from regions
- Scale auto-sizing
- Animation timing proportional to beat duration
- The `#1c1c1c` dark background (3Blue1Brown style)

---

## How context flows between scenes

**File:** `backend/app/services/production_service.py` → `_produce_sequential()`

When producing multiple scenes sequentially, each scene needs to know what the previous scenes showed — so visual elements stay consistent (same colors, same shapes, same notation).

### The continuity context

After each scene is produced, we extract its **visual state** — which objects are still on screen at the end:

```python
def _continuity_context(scene):
    # Parses the spec JSON to find which objects survived to the end
    # Returns something like:
    # "Scene 1 (Unit Circle):
    #  Concept: A point travels around a circle.
    #  Visual state at end:
    #    circle 'unit_circle' (blue) in circle_area
    #    dot 'dot' (yellow) at (-2.4, 0.0)"
```

This context is passed to the next scene's spec coder, so it knows:
- "Scene 1 ended with a blue circle on the left — I should re-establish it"
- "The concept color for the circle is blue — keep it blue"

### The rolling context

In `_produce_sequential`, contexts accumulate: Scene 2 sees Scene 1's state, Scene 3 sees Scene 1 + Scene 2's states, etc.

---

## Vision critique (visual QA)

**File:** `backend/app/agents/vision_critic.py`

After a scene is rendered and merged with audio, we take screenshots and send them to a **vision language model** (GPT-4o or Llama via Groq) for quality checking.

### What the critic checks

The critic receives:
1. **Project topic** — the overall video topic
2. **Scene narration** — what's being said
3. **Director's visual intent** — what was planned
4. **Screenshots** — 3-5 frames from the video

It responds with:
```json
{
  "passed": true/false,
  "issues": ["Arrow overlaps the equation", "Wrong color on the circle"]
}
```

### What it looks for

- **Cutoff** — objects cut off by frame edges
- **Overlap** — objects overlapping each other
- **Relevance** — does the visual match the narration?
- **Topic fit** — does the scene fit the overall video topic?
- **Static slides** — no motion (should be animated)

### Fail-open

If the vision model is unavailable or errors, the critique **passes by default** (fail-open). This prevents a dead vision model from blocking all production.

---

## Mayer's teaching principles

**File:** `backend/app/prompts/mayer.py`

Richard Mayer's research shows how people learn from words + pictures. We embed a condensed version of his 12 principles into the Writer, Director, and SpecCoder prompts.

### The principles we use

**Goal 1 — Reduce extraneous processing:**
- **Coherence**: remove anything that doesn't support the current idea
- **Signaling**: highlight what matters right now (use Indicate/Circumscribe)
- **Redundancy**: don't show text AND narrate it — the voice carries the explanation, the visual carries the evidence

**Goal 2 — Manage essential processing:**
- **Segmenting**: one idea per beat — never stack two ideas
- **Pre-training**: name the element before animating it
- **Modality**: narration + animated visual (not narration + on-screen paragraph)

**Goal 3 — Foster generative processing:**
- **Spatial contiguity**: labels must be adjacent to their objects
- **Temporal contiguity**: visuals appear WHEN the narration mentions them
- **Multimedia**: pair every verbal claim with a visual counterpart
- **Personalization**: conversational narration ("we", "you", "notice how...")

### Where they're embedded

- **Writer prompt** — hook first, concrete before abstract, one claim per scene
- **Director prompt** — concrete hook, show-then-name, build across scenes
- **SpecCoder prompt** — coherence, signaling, spatial/temporal contiguity, redundancy

---

## Treatment markdown

**File:** `backend/app/pipeline/treatment.py`

After the spec is compiled, we auto-generate a **human-readable treatment** for each scene. This is a markdown document describing:

1. **Overview** — what the scene explains
2. **Phases** — table of beats with names, durations, descriptions
3. **Layout** — ASCII diagram of the spatial arrangement
4. **Area Descriptions** — what goes in each region
5. **Notes** — timing, background, assumptions

### Example output

```markdown
# Unit Circle and Sine Wave

## Overview
A point travels around a unit circle; its y-coordinate traces a sine wave.

## Phases
| # | Phase Name | Duration | Description |
|---|-----------|----------|-------------|
| 1 | Title + opening | ~3.2s | set_title "Unit Circle", add circle (blue) at left |
| 2 | Build-up | ~5.1s | add_axes on right, add dot (yellow) |
| 3 | Rotation / motion | ~12.4s | rotate dot 2 turns over 4s |
| 4 | Highlight | ~4.8s | animate indicate on sine curve |

## Layout
┌─────────────────────────────────────┐
│  ┌──────────────┐  ┌──────────────┐ │
│  │ circle_area  │  │  wave_area   │ │
│  │    (left)    │  │   (right)    │ │
│  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────┘
```

### Where it's stored

- `treatment_md` column on the `scenes` table
- Returned in the `SceneOut` API response
- Shown as a collapsible "Treatment" tab in the SceneCard frontend

---

## How agents talk to each other (SSE events)

**File:** `backend/app/pipeline/events.py`

The backend streams real-time updates to the frontend via **Server-Sent Events (SSE)**.

### Event types

```json
{
  "type": "workflow",
  "scene_id": "abc123",
  "scene_idx": 0,
  "agent": "SpecCoder",
  "node": "specgen",
  "message": "Compiled spec into 64 lines of Manim code",
  "details": {"compiled_code": "from manim import *..."}
}
```

### What the frontend shows

- **AgentWorkflow** component — live task list with running/done/pending status
- **SceneCard** — per-scene video, narration editor, spec/code/treatment accordions
- **SiriOrb** — animated indicator showing if the pipeline is thinking/idle/errored

---

## Key files and what they do

### Backend

| File | What it does |
|------|-------------|
| `app/agents/studio_graph.py` | Writer → Director → Producer pipeline |
| `app/agents/scene_graph.py` | Per-scene LangGraph pipeline (TTS → spec → render → critique) |
| `app/agents/vision_critic.py` | Screenshot-based visual QA using vision LLMs |
| `app/agents/math_expert.py` | Math verification + correction for scene specs |
| `app/agents/llm.py` | LLM wrappers (Groq, router, fallback) |
| `app/prompts/writer.py` | Writer agent prompt |
| `app/prompts/director.py` | Director agent prompt |
| `app/prompts/producer.py` | Producer agent prompt |
| `app/prompts/spec_coder.py` | Spec coder prompt (narration → SceneSpec JSON) |
| `app/prompts/coder.py` | Raw coder prompt (narration → Manim code directly) |
| `app/prompts/fixer.py` | Code fixer prompt |
| `app/prompts/mayer.py` | Mayer's multimedia learning principles |
| `app/schemas/spec.py` | SceneSpec data model + validation |
| `app/schemas/__init__.py` | Scene, Storyboard, Project schemas |
| `app/pipeline/spec_compiler.py` | Deterministic SceneSpec → Manim code compiler |
| `app/pipeline/treatment.py` | Deterministic treatment markdown generator |
| `app/pipeline/events.py` | SSE event publishing |
| `app/pipeline/video.py` | Video rendering, stitching, merging |
| `app/pipeline/frames.py` | Frame extraction for vision critique |
| `app/pipeline/renderer.py` | Manim rendering wrapper |
| `app/pipeline/telemetry.py` | LLM call logging |
| `app/services/production_service.py` | Orchestrates scene production + stitching |
| `app/services/storyboard_service.py` | Runs studio pipeline + persists scenes |
| `app/db/models.py` | SQLAlchemy models (Project, Scene, Message) |
| `app/db/repositories.py` | Database CRUD operations |
| `app/db/session.py` | Database engine + migrations |
| `app/config.py` | Settings (env vars, model names, feature flags) |
| `app/main.py` | FastAPI app + routes |

### Frontend

| File | What it does |
|------|-------------|
| `src/app/project/[id]/page.tsx` | Main project page — SSE consumer, layout |
| `src/components/AgentWorkflow.tsx` | Live agent task list with progress |
| `src/components/SceneCard.tsx` | Per-scene card with video, narration, spec/code/treatment |
| `src/components/smoothui/ai-tool-call/index.tsx` | Animated tool call display |
| `src/components/smoothui/ai-reasoning/index.tsx` | Collapsible reasoning display |
| `src/components/smoothui/ai-task-list/index.tsx` | Task list with status badges |
| `src/components/smoothui/siri-orb/index.tsx` | Animated orb indicator |
| `src/lib/api.ts` | API client + SSE consumer |

---

## How to run it

### Prerequisites

- Python 3.12+
- Node.js 18+
- Manim Community Edition (`pip install manim`)
- A Groq API key (for LLM calls)
- Optional: OpenRouter key (for vision model), ElevenLabs key (for TTS)

### Backend

```bash
cd backend
cp .env.example .env
# Edit .env with your API keys
uv sync                    # install dependencies
uv run uvicorn app.main:app --reload   # start server on :8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                # start dev server on :3000
```

### Environment variables

| Variable | Required | What it does |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Primary LLM API key |
| `OPENROUTER_API_KEY` | No | Vision model API key |
| `ELEVENLABS_API_KEY` | No | TTS voice generation |
| `DATABASE_URL` | No | SQLite path (default: `./animind.db`) |
| `MEDIA_DIR` | No | Where rendered videos are stored |

---

## Glossary

| Term | Meaning |
|------|---------|
| **Agent** | An AI model with a specific job (Writer, Director, SpecCoder, etc.) |
| **LangGraph** | A library for building state-machine workflows with AI agents |
| **SceneSpec** | A JSON blueprint describing what a scene should show, beat by beat |
| **Spec compiler** | Converts SceneSpec JSON into runnable Manim Python code |
| **Manim** | A Python library for mathematical animations (created by 3Blue1Brown) |
| **Beat** | One narration thought + its visual actions (like a shot in filmmaking) |
| **Treatment** | A human-readable markdown description of a scene's timing and layout |
| **SSE** | Server-Sent Events — how the backend streams real-time updates to the frontend |
| **Vision critique** | Screenshot-based quality check using a vision language model |
| **MathCheck** | Verification that formulas and numbers in the spec match the narration |
| **Continuity context** | A summary of what previous scenes showed, carried forward to keep visuals consistent |
| **Structured output** | Forcing an LLM to return valid JSON matching a specific schema |
| **Fail-open** | If a check fails (e.g. vision model down), pass by default rather than block production |
| **Rolling context** | Accumulating visual state from all prior scenes so each new scene stays consistent |

---

## Design Decisions — Why everything is the way it is

This section explains the **reasoning** behind every major architectural choice. If you're new to AI/LLM systems, this is the most important section to read.

---

### Why a multi-agent system instead of one big prompt?

**Problem:** A single LLM call trying to plan a script, write visuals, generate code, and check quality would produce mediocre results at everything.

**Decision:** Split the work into specialized agents, each doing ONE thing well.

**Why it works:**
- The **Writer** only thinks about pedagogy (how to teach), not code
- The **Director** only thinks about visuals (what to show), not narration
- The **SpecCoder** only thinks about the declarative spec, not Manim syntax
- Each agent gets a focused prompt with domain-specific rules

**Analogy:** Like a film studio — the screenwriter doesn't operate the camera, the cinematographer doesn't edit, the editor doesn't act. Specialization beats generalization.

---

### Why a declarative spec (SceneSpec) instead of direct codegen?

**Problem:** LLMs writing Manim code directly produce lots of bugs — wrong API calls, broken positioning, missing imports, syntax errors. Every scene needs 3-5 fix retries.

**Decision:** Ask the LLM to write a **JSON blueprint** (SceneSpec) instead, then **compile** it deterministically into Manim code.

**Why it works:**
- JSON is easier for LLMs to get right than Python code (fewer syntax rules)
- The compiler is **deterministic** — same spec always produces same code (no randomness)
- The compiler handles all the Manim boilerplate (imports, class structure, positioning math)
- We can **validate** the spec before compiling (check ids, positions, references)
- If validation fails, we retry with feedback — much cheaper than fixing code

**Trade-off:** The spec can only describe actions from a fixed op-set (add_shape, rotate, connect, etc.). Complex custom Manim (ValueTracker, custom curves) can't be expressed declaratively. That's why we have the **fallback to raw codegen** — when the spec can't express what's needed, we let the LLM write code directly.

---

### Why sequential scene production instead of parallel?

**Problem:** If all scenes are produced in parallel, Scene 3 doesn't know what Scene 1 showed. Colors, shapes, and notation drift between scenes.

**Decision:** Produce scenes **sequentially** — each scene carries the visual state of all prior scenes as context.

**Why it works:**
- Scene 2 knows Scene 1 ended with a blue circle → it re-establishes the blue circle
- The "rolling context" accumulates: Scene N sees scenes 1 through N-1
- This is how real animation studios work — later scenes reference earlier ones

**Trade-off:** Slower (can't parallelize). But quality matters more than speed for educational content.

---

### Why a vision critic with screenshots instead of text-only QA?

**Problem:** A text-only model can check if the narration is correct, but can't check if the **animation looks right** — are objects overlapping? Is the layout balanced? Is there motion?

**Decision:** Extract **screenshots** from the rendered video and send them to a **vision language model** (GPT-4o or Llama) for visual QA.

**Why it works:**
- The vision model can SEE the actual frames — it catches visual bugs text models miss
- It checks: cutoff, overlap, relevance to narration, topic fit, static slides
- Screenshots are cheap (3-5 frames per scene) vs. analyzing every frame

**Trade-off:** Vision models are slower and more expensive than text models. That's why we only critique after rendering (not after spec generation) — we check the actual output, not a plan.

---

### Why fail-open on the vision critic?

**Problem:** If the vision model API is down (rate limited, network error), the entire production pipeline blocks. Every scene waits forever for a critique that never comes.

**Decision:** If the vision model is unavailable or errors, **pass the scene by default** (fail-open).

**Why it works:**
- Production keeps moving even when external services are flaky
- A dead vision model shouldn't block all video generation
- The user can still see the video and manually check quality
- We log the skip reason so it's visible, not silent

**Trade-off:** Some low-quality scenes might slip through. But blocking all production is worse than letting a few bad scenes through.

---

### Why Mayer's principles are embedded in prompts, not enforced in code?

**Problem:** Teaching quality is subjective — you can't write a function that checks "is this explanation clear?" The spec compiler can check structural validity, but not pedagogical quality.

**Decision:** Embed Mayer's multimedia learning principles as **text instructions** in the Writer, Director, and SpecCoder prompts.

**Why it works:**
- LLMs follow text instructions well — "one idea per beat" is enforceable via prompt
- The principles are research-backed (200+ experiments) — not guesswork
- They're condensed to ~200 tokens so they don't crowd out the main prompt

**What can't be enforced:**
- "Is the explanation actually clear?" — only a human can judge this
- "Does the visual metaphor match the concept?" — the vision critic catches obvious mismatches, but subtle ones slip through

---

### Why SQLite instead of PostgreSQL?

**Problem:** For a prototype/personal project, PostgreSQL is overkill — it requires a separate server, configuration, and maintenance.

**Decision:** Use **SQLite** (a single file database) for simplicity.

**Why it works:**
- Zero configuration — just a file on disk
- `create_all()` + inline migrations in `init_db()` handle schema changes
- Good enough for single-user or small-team usage
- Easy to backup (copy one file)

**Trade-off:** Not suitable for production multi-user deployment. Would need to switch to PostgreSQL for that.

---

### Why SSE instead of WebSockets for real-time updates?

**Problem:** The frontend needs to show live progress as agents work (each step takes 10-60 seconds). How does the backend push updates?

**Decision:** Use **Server-Sent Events (SSE)** — a one-way push channel from server to client.

**Why it works:**
- Simpler than WebSockets (no bidirectional protocol)
- Built into HTTP — works through proxies, load balancers, CORS
- The frontend only needs to **receive** updates, not send them (during production)
- `EventSource` API handles reconnection automatically

**Trade-off:** If the frontend needed to send real-time messages back (e.g., "cancel this scene"), WebSockets would be better. But for our read-only monitoring, SSE is perfect.

---

### Why the spec has validation with retry instead of one-shot?

**Problem:** LLMs sometimes emit broken JSON — missing ids, wrong field names, references to non-existent objects. A broken spec produces broken code.

**Decision:** After generating a spec, **validate** it (check ids, references), and if it fails, **feed the issues back** to the LLM and ask it to regenerate (up to 2 retries).

**Why it works:**
- The validator catches ~90% of common spec errors (missing ids, broken references)
- Feeding issues back is much cheaper than retrying from scratch
- 2 retries is enough — if it still fails after 2 tries, the scene is too complex for the spec system and we fall back to raw codegen

**Trade-off:** Adds 1-2 extra LLM calls per broken spec. But the alternative (compiling broken specs) wastes even more tokens on failed renders + fix loops.

---

### Why the treatment markdown is generated deterministically, not by an LLM?

**Problem:** The treatment describes timing, layout, and phases — all of which are already computed in the spec. Asking an LLM to re-describe what the spec already says wastes tokens and introduces hallucination risk.

**Decision:** Generate the treatment **deterministically** from the spec JSON + audio duration — no LLM call needed.

**Why it works:**
- Free (no API cost)
- Instant (no latency)
- 100% accurate (it reflects the actual spec, not an LLM's interpretation of it)
- Can be regenerated anytime without re-running the pipeline

---

### Why the vision critic doesn't see previous scenes' frames

**Problem:** Cross-scene inconsistency (wrong color, missing object) should be caught by the critic. But sending ALL frames from ALL scenes would be too many images for the vision model.

**Decision:** The critic only sees the **current scene's** frames + narration + visual description + project topic. It does NOT see previous scenes.

**Why it works (partially):**
- Keeps the vision model's input small and focused
- The project topic gives enough context for relevance checking
- The continuity context (passed to the spec coder) handles consistency at the spec level

**Known gap:** The critic can't catch "Scene 2 re-introduces the circle in red when Scene 1 had it blue" because it doesn't see Scene 1's frames. This is a known limitation — the continuity context helps but isn't foolproof.

---

### Why the spec compiler is deterministic (no randomness)?

**Problem:** If the compiler used an LLM to translate spec → code, it would introduce randomness — same spec could produce different code each time, making debugging impossible.

**Decision:** The compiler is **pure Python** with no LLM calls — it maps spec ops to Manim code templates mechanically.

**Why it works:**
- Same spec always produces same code (reproducible)
- Faster than LLM-based translation (milliseconds vs seconds)
- Cheaper (no API cost)
- Easier to debug (if the output is wrong, fix the compiler, not the LLM)

---

### Why the project uses Groq as the primary LLM provider?

**Problem:** Most LLM APIs (OpenAI, Anthropic) are expensive for a prototype that makes many calls per scene (spec + math check + critique + fix).

**Decision:** Use **Groq** as the primary provider — it offers free-tier access to Llama and Mixtral models with fast inference.

**Why it works:**
- Free tier covers development and light usage
- Fast inference (Groq's custom hardware)
- Fallback to OpenRouter for vision model (Groq doesn't have vision)
- Backup Groq API key for when the primary hits daily token cap

**Trade-off:** Free-tier models are smaller than GPT-4, so quality is lower. That's why the spec system + validation + retry is important — it compensates for weaker models with structured output and retries.
