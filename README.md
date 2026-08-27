# AniMind

**AI-generated animated explainer videos** — enter a topic, get a 3Blue1Brown-style
narrated animation with an editable storyboard. Full-stack prototype powered by the Groq API.

## How it works

A multi-agent "animation studio" pipeline (LangGraph + ChatGroq):

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

- **Writer/Director/Producer** collaborate on a pedagogy-structured storyboard with
  concrete, renderable visual descriptions.
- **SpecCoder** emits declarative scene beats; the compiler enforces the house style,
  frame bounds, region layout and timing. Raw Manim code is the fallback path.
- **Fixer** feeds renderer errors back to the LLM until the scene renders.
- If TTS hits rate limits/outage, scenes degrade gracefully to **muted video with subtitles**.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14, Tailwind, SSE live progress |
| Backend | FastAPI, SQLAlchemy (repository/service layers), uv |
| Agents | LangGraph, langchain-groq (gpt-oss-120b), optional AgentRouter vision QA |
| Media | Manim CE, moviepy, Groq TTS (Orpheus) |

## Run it

Backend (requires [uv](https://docs.astral.sh/uv/), ffmpeg, and a Groq API key):

```bash
cd backend
uv sync
cp .env.example .env         # add your ANIMIND_GROQ_API_KEY
uv run uvicorn app.main:app --port 8000
```

Frontend:

```bash
cd frontend
npm i
npm run dev                  # http://localhost:3000
```

Flow: enter a topic → storyboard appears → **Produce all scenes** → watch live
per-scene progress → edit narration / regenerate scenes → play & download the MP4.

## Repo map

```
backend/app/
├── main.py                  routes (controller)
├── services/                storyboard_service, production_service (business logic)
├── db/                      models → repositories (all SQL)
├── agents/                  studio_graph (Writer⇄Director⇄Producer),
│                            scene_graph (TTS→spec/codegen→render→merge→vision QA), tts, llm
├── prompts/                 the core IP: writer/director/producer/coder/fixer
├── pipeline/                renderer (manim), video (moviepy), events (SSE bus)
frontend/src/
├── app/page.tsx             topic input
├── app/project/[id]/        storyboard editor + player
└── components/SceneCard.tsx per-scene status/edit/regenerate
research/                    arXiv papers this design draws on
PLAN.md                      architecture & roadmap
QUALITY_NOTES.md             tracked video-quality findings per iteration
```

## Roadmap

- **v1.5** Vision critic (frame screenshots → Llama-4 Scout → layout fixes) · Researcher
  agent (web search via `groq/compound`) · Code Reviewer agent (static checks before render)
  · Evals + golden-set CI (render success rate, frame-variance, LLM-as-judge) · LangSmith tracing
- **v2** Consistency editor · narration QA · thumbnail/title agent · Celery queue · auth ·
  template themes · ElevenLabs voices

See `PLAN.md` for the full architecture and `QUALITY_NOTES.md` for iteration findings.
