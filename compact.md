Let me carefully parse this long conversation to understand what's happened. The user is building "AniMind" - a full-stack prototype that turns topics into 3Blue1Brown-style narrated animated explainer videos using Manim.

The conversation started with a context dump about the project, then the agent did work on:
1. Fixing a crash bug in scene_graph.py (TypeError: 'NoneType' object is not a mapping from LangGraph emitting {node: None} when node returns empty dict)
2. Fixing stale render artifact bug (renderer could accept old MP4)
3. Fixing project completion integrity (all scenes must be ready)
4. Continuity propagation fixes
5. Vision QA retry routing

Then the user asked for few-shot examples from the internet - agent researched Manim CE examples and added:
- research/MANIM_FEW_SHOTS.md
- QUALITY_FEW_SHOTS in coder.py
- high-quality visual grammar in spec_coder.py

Then the user asked to make the frontend like ChatGPT UI with widgets (Horizon UI template link). Agent rebuilt frontend as ChatGPT-style studio with Horizon-inspired light theme.

Then user said use npx shadcn@latest add @smoothui/chat-template from smoothui.dev. Agent installed SmoothUI registry components via npx smoothui-cli@latest add chat-template (since shadcn CLI failed due to ui.shadcn.com timeout):
- 17 components installed under frontend/src/components/smoothui/
- Added motion, lucide-react deps
- Added components.json
- Added src/lib/utils.ts
- Added shadcn-compatible Tailwind CSS variables

Then rebuilt pages to use SmoothUI components: AIPromptInput, AISuggestions, SiriOrb, AIConversation, AILoader, AIMessage, AgentWorkflow, etc.

User said "every component from input box to drop down must be shadcn so everything is coherent" - agent added shadcn UI primitives manually:
- src/components/ui/button.tsx, input.tsx, textarea.tsx, badge.tsx, card.tsx, progress.tsx, select.tsx
- Radix deps installed: @radix-ui/react-select, @radix-ui/react-progress, @radix-ui/react-slot, class-variance-authority, clsx, tailwind-merge
- Replaced native select/input/textarea/buttons with shadcn primitives

User reported Groq 429 daily token cap - agent added fallback model routing:
- fallback_model = qwen/qwen3.8-27b (config)
- fallback_llm() in llm.py
- structured_call and llm_with_retry switch to fallback on "tokens per day"/"tpd" errors

Workflow observability: backend now emits "workflow" events via SSE:
- events.py: history deque, history() function
- studio_graph.py: Writer/Director/Producer publish workflow events
- scene_graph.py: run_scene on_update callback
- production_service.py: on_update mapping node->agent, _workflow_message
- main.py: /api/projects/{id}/events/history, /api/config endpoints
- storyboard_service.py: create_project returns immediately, generate_storyboard runs async (background task); project creation now immediate so SSE can stream storyboard generation
- main.py POST /api/projects creates project + spawns background generate_storyboard task instead of blocking

Frontend:
- AgentWorkflow.tsx: agent room UI with AIReasoning, AITaskList, AIToolCall, AIMessage
- project page: SSE streaming, workflow history, config panel
- api.ts: getWorkflowHistory, getPublicConfig, WorkflowEvent, PublicConfig types

Frontend hosting issues: multiple stale next dev/start processes interfere with .next. Final state: production npm run start on 127.0.0.1:3000. Last user action: "stop port 3000" which agent did.

Wait, actually the last commands: "stop port 3000" - agent confirmed "port 3000 stopped". Then user reported a running scene failure with Manim error. Then more fixes happened. Then at the very end:

User: "it works succesfully now but still there is visual in consistency is there any new reseach on it or should i use better modellike opus"
Agent: started researching - fetched arXiv pages for Manimator (2507.14306), PhysicsSolutionAgent (2601.13453), LLM2Manim (2604.05266), Claude Opus page.

User: "ignore any sensitive stuff"
Agent: "Understood. I'll ignore sensitive values, avoid displaying or repeating keys/tokens, and refer to them only by redacted names such as ANIMIND_GROQ_API_KEY or ANIMIND_ROUTER_API_KEY."

So the current state at end of conversation: agent is in the middle of researching visual consistency in LLM-generated Manim animations / whether to use a better model like Opus. The research task (subagent) was aborted once, then agent fetched several pages directly. The final message is just acknowledging to ignore sensitive stuff.

The user's last substantive request: visual inconsistency - is there new research on it, or should they use a better model like Opus? So the next move is to complete that research and provide a recommendation.

Key technical state:
- Backend running on 127.0.0.1:8000 (uvicorn)
- Frontend: port 3000 was stopped per user request (last explicit check). The agent had restarted frontend multiple times. After "stop port 3000" the frontend was stopped. Later the agent checked curl frontend=200 at one point... Actually after the stop-port-3000 request, the remaining conversation is about backend fixes. Let me check: after "stop port 3000" -> agent confirmed stopped. Then user reported render failure in the workflow panel (the visual text follows). Agent made backend fixes and did backend checks only; no frontend restart visible after that. Actually there was a curl frontend=200 in one of the later verification batches? Let me scan... Near the end: curl -s -o /dev/null -w 'frontend=%{http_code}\n' -m 10 http://127.0.0.1:3000/ returned frontend=200 in one batch ("The frontend and API are healthy..."). Hmm, that was after stop-port-3000? Let me check ordering.

Ordering near the end:
1. User: "stop port 3000" → agent killed PIDs, confirmed "port 3000 stopped"
2. User pastes render failure (set_start_and_end_points TypeError) → agent fixed normalize_manim_code
3. User: "what is the wasiest thing i could ask to make" → agent answered (suggest easy prompts)
4. User pastes workflow with "Scene could not produce valid candidate" and UP.rotate error → agent fixed normalize for UP.rotate, placeholder rejection
5. User pastes circle area failure → agent added circle-area few-shot, preflight_visual_code, fixer loop changes
6. Tests pass 15
7. User: "it works succesfully now but still there is visual in consistency is there any new reseach on it or should i use better modellike opus" → agent researching
8. User: "ignore any sensitive stuff" → agent acknowledgment

Wait, in step 2-5, was the frontend restarted? The agent mostly did backend restarts. There was one health-check batch that included curl frontend=200 - but that may have been before stop port 3000? Actually no. Let me re-read.

The batch after test fix:
curl -s -m 10 http://127.0.0.1:8000/api/health; printf '\n'; curl -s -m 10 http://127.0.0.1:8000/api/config; printf '\n'; curl -s -o /dev/null -w 'frontend=%{http_code}\n' -m 10 http://127.0.0.1:3000/
returned frontend=200. But that was BEFORE the user's "stop port 3000"? Hmm no. Let me look at where stop port 3000 happened.

Actually the "stop port 3000" message appears after the agent's long final summary about dropdown fix and models/TTS, and before the user's long render-failure paste. So:

1. ... frontend rebuild, dropdown fix verification (home=200)
2. Agent summary about native dropdown fix + rate limit + models
3. User: "stop port 3000" → stop confirmed
4. User pastes error (set_start_and_end_points) → backend fixes
5. easy prompts Q
6. UP.rotate failure
7. circle area failure + fixes
8. "it works successfully now but still visual inconsistency... better model like opus?"
9. ignore sensitive stuff

So at end: frontend is STOPPED on port 3000. Backend running on 8000. The user is asking about visual consistency research / better model recommendation. The agent's research is incomplete (fetched Manimator, PhysicsSolutionAgent, LLM2Manim abstracts, Claude Opus page — but the subagent research task was aborted, results not synthesized yet).

Important details to preserve:
- URLs: 
  - https://arxiv.org/abs/2507.14306 (Manimator)
  - https://arxiv.org/abs/2601.13453 (PhysicsSolutionAgent)
  - https://arxiv.org/abs/2604.05266 (LLM2Manim)
  - https://www.anthropic.com/claude/opus (Claude Opus 4.8; note: Claude Opus 5 announced as "step-change")
- research/ has PDFs already
- Manimator findings: structured scene description + LLM translates to Manim
- PhysicsSolutionAgent: 15 quantitative checks assessment pipeline
- LLM2Manim: symbol ledger to keep symbols consistent (this is the key continuity relevance!), constrained prompt templates, segmenting/signaling/dual coding
- The user asked: new research on visual consistency? or better model like Opus?

Key config:
- Models: planner/coder: openai/gpt-oss-120b; fixer: openai/gpt-oss-20b; fallback: qwen/qwen3.8-27b; vision: claude-opus-4-8 via AgentRouter; TTS: canopylabs/orpheus-v1-english voice autumn
- vision_max_attempts: 2
- tts_enabled: True
- sequential_scenes: True
- codegen_mode: spec
- max_scene_retries: 5
- vision frames: 3 × 480px

Backend .env keys: ANIMIND_GROQ_API_KEY, ANIMIND_ROUTER_API_KEY, ANIMIND_ROUTER_BASE_URL (values must NOT be repeated — user said ignore sensitive stuff)

Frontend component inventory:
- src/components/smoothui/: ai-approval, ai-artifact, ai-context-meter, ai-conversation, ai-core, ai-diff, ai-loader, ai-message, ai-prompt-input, ai-reasoning, ai-response, ai-sources, ai-suggestions, ai-task-list, ai-tool-call, chat-template (chat-data.ts, chat-sidebar.tsx, chat-thread.tsx, index.tsx), siri-orb
- src/components/ui/: button, input, textarea, badge, card, progress, select
- src/components/: SceneCard.tsx, AgentWorkflow.tsx (StudioShell.tsx deleted)
- src/app/page.tsx (Home composer), src/app/project/id/page.tsx
- src/lib/api.ts, src/lib/utils.ts
- components.json (registry @smoothui: https://smoothui.dev/r/{name}.json)
- deps: lucide-react, motion, @radix-ui/react-select, @radix-ui/react-progress, @radix-ui/react-slot, class-variance-authority, clsx, tailwind-merge
- tsconfig target es2017 added
- globals.css: shadcn HSL tokens light/dark

Backend recent changes (reliability):
- scene_graph.py: run_scene skips None updates; critique/accept/fail routing; qa_attempts/qa_exhausted; TTS entry node; merge→critique; accept node; fix_code fresh-codegen fallback with feedback; generate_code(feedback) param; spec fallback
- renderer.py: normalize_manim_code (set_start_and_end_points→put_start_and_end_on; UP/DOWN/LEFT/RIGHT.rotate→rotate_vector), preflight_visual_code (placeholder + repeated shapes), per-attempt isolated temp media dir, unique output name, ast validation (VideoScene, construct, self.play/add), stable write via temp + os.replace, deletes stale scene.mp4/scene_final.mp4
- production_service.py: produce_project reset, _produce_sequential dict results, strict all-scenes restitch with atomic temp file + os.replace, _discard_final, project_artifacts_ready, reconcile_ready_projects, continuity context fallback (spec_json or JSON of visual_desc+code_excerpt)
- events.py: _history deque, history()
- studio_graph.py: structured_call fallback on TPD, workflow events
- main.py: _active_projects set lock (409), async storyboard generation (POST /api/projects returns immediately, background generate_storyboard), /api/config, /api/projects/{id}/events/history, scene_video requires status ready, video requires project ready + artifacts
- storyboard_service.py: create_project (sync) + generate_storyboard (async background; publishes workflow events, marks project failed on error)
- llm.py: _groq helper, fallback_llm
- config.py: fallback_model, tts_enabled, vision_max_attempts; SettingsConfigDict; still has old class Config removed? Yes migrated to model_config.
- prompts: coder.py QUALITY_FEW_SHOTS (A-D incl. circle-area Sector pattern), fixer.py manim CE API notes, spec_coder.py visual grammar

Tests: backend/tests/test_reliability.py — 15 passed; conftest.py with sys.path; pyproject dependency-groups dev pytest

Known failing/ambient items:
- Groq daily token cap: gpt-oss-120b limit 200000/day was exhausted repeatedly; fallback to qwen/qwen3.8-27b works (verified in logs). Retry SDK backoff ~29s-8s.
- llm.py check uses getattr(llm, "model_name") (fixed from model? there were two edits: earlier getattr(llm, "model", None), later patched to getattr(llm, "model_name", None)) — need to confirm final; last patch in conversation applied model_name. Actually read showed chat_models.py has model_name alias. Fine.
- Frontend port 3000 currently STOPPED (user asked).
- Existing DB projects: several ready (f3ae1b370f89 etc.), some failed/invalidated. Recent test projects: 63d5e8fb0df1 (failed), 924e11f6507c (failed), a7797144c140 (failed), fa352e5d828f (satellite, drafting w/ 4 scenes), 62e0aa3637ae (user project).
- Backend log tail shows regeneration running/waiting on 429 backoff at times.
- In-memory event history is lost on backend restart (deque in events.py).

Active research for the final question: visual consistency - the agent fetched:
- Manimator: pipeline: LLM interprets input → structured scene description → another LLM translates to Manim; scene graph consistency aspects.
- PhysicsSolutionAgent: automated assessment across 15 quantitative checks.
- LLM2Manim: constrained prompt templates, symbol ledger (symbols consistent across scenes), Mayer principles.
- Claude: Opus 4.8 hybrid reasoning 1M context; Opus 5 announced as step-change (newer); AgentRouter currently serving claude-opus-4-8 as vision model.
- Research was not yet synthesized into a recommendation.

So the immediate next move: answer the user's question - synthesize research findings (Manimator element layout, PSA 15-check pipeline, LLM2Manim symbol ledger) and recommend whether Opus helps. Key pragmatic recommendations: LLM2Manim's "symbol ledger" = formalize the scene-to-scene context (which AniMind partially does via spec_json + visual language). Opus likely helps at critique/planning stage but cost; keep deterministic compiler; consider a "concept ledger" table shared across scenes in prompts plus stronger vision QA. Also note AgentRouter already routes to claude-opus-4-8 for vision (so Opus wiring is basically available via router_api_key... but llm.py only uses Groq for text; the router is used only in vision_critic). The Sonnet/Opus plan from context: add ANTHROPIC_API_KEY, uv add anthropic, wire fallback in agents/llm.py, switch vision_model — agreed in principle, not implemented. Note the router already provides claude model for vision.

Also mention: sensitive stuff — don't display keys (ANIMIND_GROQ_API_KEY, ANIMIND_ROUTER_API_KEY values redacted).

Now structure the summary per template:

Objective
- Build/finish AniMind: reliable spec→Manim pipeline with visual continuity, and a coherent shadcn/SmoothUI ChatGPT-style frontend with live SSE agent workflow. Latest open question: how to fix remaining cross-scene visual inconsistency — new research or switch to a stronger model (e.g., Claude Opus).

Important Details
- Stack, repo path
- Command to install SmoothUI: npx smoothui-cli@latest add chat-template (shadcn CLI fails: ui.shadcn.com timeout; @smoothui/chat-template not on npm)
- All active UI controls now shadcn primitives; SmoothUI for animated AI surfaces
- Models config, fallback behavior
- TTS fallback
- Vision QA cap
- Event/history endpoints
- Async project creation now returns immediately; storyboard generated in background
- Port status: frontend stopped on 3000 (user-requested); backend up on 8000
- Research sources fetched
- Sensitive: don't echo keys
  Reference only by var names.

Work State
Completed
- Many items: graph None-update fix, stale-render isolation, strict all-scene publication, startup reconcile, continuity context, TTS entry node, workflow SSE events + history + /api/config, async project create, fallback model for TPD, normalize_manim_code, preflight_visual_code, fixer fresh-codegen fallback, circle-area few-shot, shadcn UI primitives + SmoothUI integration, 15 tests pass, frontend lint/build pass (last build before stop)
- Research fetched (Manimator, PSA, LLM2Manim abstracts, Claude Opus page)

Active
- Answering user's visual-consistency question; research fetched but not synthesized into recommendation (subagent research task aborted → replaced with direct webfetch)

Blocked
- Groq daily cap on gpt-oss-120b (200k TPD); fallback to qwen3.8-27b active; known 429 wait in logs
- Frontend port 3000 stopped intentionally
- In-memory event history lost on backend restart

Next Move
1. Synthesize research into recommendation: LLM2Manim symbol-ledger → add persistent "concept ledger" (shape/color per concept carried via context), Manimator element-layout axis, PSA 15-check automated QA; recommend model strategy: keep deterministic compiler; optionally use Opus (via AgentRouter, already used for vision critic claude-opus-4-8; or Sonnet for structured outputs) for planning/critique only, not raw codegen; keep costs.
2. Offer to implement: concept ledger across scenes (upgrade _continuity_context to include a concepts table), maybe stronger vision QA (more frames), and re-start frontend on 3000 if user wants.
- Note: check current model names via /api/config.

Relevant Files
- backend/app/pipeline/renderer.py: normalize_manim_code, preflight_visual_code, isolated renders
- backend/app/agents/scene_graph.py: graph nodes, fix/generate feedback loop
- backend/app/agents/studio_graph.py: structured_call TPD fallback + workflow events
- backend/app/services/production_service.py: production, continuity context, strict restitch, reconcile
- backend/app/services/storyboard_service.py: async background storyboard
- backend/app/pipeline/events.py: SSE history
- backend/app/agents/llm.py + config.py: models/fallback
- backend/app/prompts/coder.py, fixer.py, spec_coder.py: few-shots
- frontend/src/components/ui/*: shadcn primitives
- frontend/src/components/smoothui/*: installed SmoothUI components (17)
- frontend/src/components/AgentWorkflow.tsx, SceneCard.tsx; frontend/src/app/page.tsx, project/id/page.tsx
- frontend/src/lib/api.ts: WorkflowEvent, PublicConfig, endpoints
- backend/.env (ANIMIND_GROQ_API_KEY, ANIMIND_ROUTER_API_KEY, ANIMIND_ROUTER_BASE_URL) — do not print values
- research/MANIM_FEW_SHOTS.md, research/*.pdf

Keep terse. Let me write it.

I should include exact URLs in next move/relevant section for research.

Also note: backend port 8000 running (uvicorn pid etc., don't need pid). Frontend port 3000 stopped.

Also the "ignore any sensitive stuff" instruction — include in Important Details: never echo API keys; refer to them by env var names only.

Model list on Groq account: meta-llama/llama-prompt-guard..., openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.6-27b, qwen/qwen3.8-27b, openai/gpt-oss-safeguard-20b.

One more check: the final fix_code change replaced old tests; final test count 15 passed. compileall OK. Backend restarted and healthy on 8000.

Also frontend build: the last npm run build succeeded (32.4 kB home, 9.91 kB project). Lint clean. But user asked to stop port 3000 and agent stopped it; no frontend restart afterward, though one batch showed frontend=200... that batch appears BEFORE "stop port 3000" actually? Let me not overstate; safest: "port 3000 stopped per user request; last successful build/lint before that; later backend-only fixes did not require frontend restart, but the running frontend on 3000 may need restart after workflow UI changes were built earlier." Actually the workflow UI changes were built and started before stop-port-3000? The workflow UI (AgentWorkflow etc.) was built in the same timeframe as the "frontend build passes" messages. Then stop port 3000 happened. So currently no frontend serving. Mark that clearly.

Also note pending: backend main.py import change to create_project alias persisted; /api/projects returns immediately with empty scenes and background task fills them; project status remains "drafting" until production (storyboard events don't flip status to something else — actually scene creation happens in background; status stays drafting; SSE workflow events stream).

Edge: generate_storyboard failure sets project failed.

Also frontend events effect changed to keep SSE open for statuses other than "ready" (so failed still streams).

OK, writing the summary now. Keep it tight but complete.
Objective
- Finish AniMind (/home/kumar-anubhav/Documents/Projects/animind/): reliable spec→Manim pipeline (Groq + Manim CE) with a coherent shadcn/SmoothUI ChatGPT-style frontend and live SSE workflow visibility.
- Latest open question from user: residual cross-scene visual inconsistency — is there new research on it, or should they switch to a stronger model (e.g., Claude Opus)?
Important Details
- Stack: FastAPI + SQLite backend, Next.js 14 + Tailwind frontend, uv + Python 3.13.14, LangGraph, Manim CE, moviepy. Backend on 127.0.0.1:8000; frontend port 3000 was stopped on user request (no frontend server currently running; last build/lint passed).
- SmoothUI install (works): npx smoothui-cli@latest add chat-template. shadcn CLI (npx shadcn@latest add @smoothui/chat-template) fails — ui.shadcn.com timeout; package not on npm. Installed 17 components under frontend/src/components/smoothui/.
- All active form/UI controls are now local shadcn primitives (ui/button|input|textarea|select|badge|card|progress); SmoothUI remains for animated AI surfaces (orb, prompt input, conversation, message, tool-call, reasoning, task list, loader).
- Models (via /api/config): planner/coder openai/gpt-oss-120b, fixer openai/gpt-oss-20b, daily-cap fallback qwen/qwen3.8-27b, vision claude-opus-4-8 via AgentRouter (3×480px frames), TTS canopylabs/orpheus-v1-english (voice autumn). tts_enabled=True, codegen_mode=spec, sequential_scenes=True, max_scene_retries=5, vision_max_attempts=2.
- Groq free tier was repeatedly hitting daily cap (200k TPD on gpt-oss-120b, e.g. Used 199973); structured_call/llm_with_retry now auto-switch to fallback_model on tokens per day/tpd (verified live: fallback produced a 4-scene storyboard). SDK 429 backoff (~8–29s) still occurs.
- TTS fallback = muted video with burned-in captions (merge_with_captions); exposed in /api/config tts.fallback.
- /api/projects now returns immediately (project created, storyboard generated in an async background task so Writer/Director/Producer events stream over SSE).
- Events: type:"workflow" published per node (agent, node, message, details, scene_id/scene_idx), history endpoint /api/projects/{id}/events/history, config endpoint /api/config. History is in-memory (lost on restart).
- Renderer guards: per-attempt isolated temp media dir + unique output name, normalize_manim_code (set_start_and_end_points(→put_start_and_end_on(; UP|DOWN|LEFT|RIGHT.rotate(→rotate_vector(...)), preflight_visual_code (placeholder + repeated-shapes-without-transform rejection), AST validation (VideoScene/construct/self.play), stale scene.mp4/scene_final.mp4 deletion, atomic os.replace.
- Fixer loop: invalid/placeholder fixer output → fresh codegen with QA feedback (never re-renders the rejected composition).
- Project publication is strict: all scenes ready + real files; startup reconcile_ready_projects() invalidates legacy partial projects.
- Sensitive values must not be repeated/displayed — refer only by var names: ANIMIND_GROQ_API_KEY, ANIMIND_ROUTER_API_KEY, ANIMIND_ROUTER_BASE_URL (backend/.env).
- Research pages already fetched (not yet synthesized into a recommendation):
- Manimator https://arxiv.org/abs/2507.14306 (structured scene description → LLM to Manim)
- PhysicsSolutionAgent https://arxiv.org/abs/2601.13453 (15 quantitative automated checks pipeline)
- LLM2Manim https://arxiv.org/abs/2604.05266 (constrained prompt templates + symbol ledger for cross-scene symbol consistency, Mayer principles)
- Claude https://www.anthropic.com/claude/opus (Opus 4.8 hybrid reasoning 1M ctx; Opus 5 announced as step-change)
Work State
Completed
- Graph crash fix: LangGraph updates stream emits {node: None} for empty-dict nodes; run_scene skips falsy updates; critique/accept/fail/merge routing complete.
- Spec pipeline + deterministic compiler (spec_compiler.py) with region boxes/slot grid, _fit/_keep_in_frame helpers, axes sized to regions, label placement below targets, title-only rejection.
- Reliability: stale-render prevention, strict all-scenes restitch (atomic temp → os.replace), artifact reconcile on startup, per-project _active_projects 409 locks, continuity context rolled forward (spec_json or JSON of visual_description+code_excerpt), scene regeneration rebuilds downstream.
- Workflow observability: backend workflow events + history; AgentWorkflow.tsx "Live agent room" (SiriOrb, AIReasoning, AITaskList, AIToolCall list, model/TTS config footer).
- Frontend: ChatGPT-style composer home (AIPromptInput, shadcn Select/Input, SiriOrb, AISuggestions), project page (AIConversation, SceneCard = shadcn Card + AIMessage, SSE workflow streaming, failed-scene "Rerender failed scene").
- Manim few-shots: research/MANIM_FEW_SHOTS.md (official MIT-licensed Manim CE sources), QUALITY_FEW_SHOTS in prompts/coder.py (patterns A–D incl. circle-area Sector pattern), visual grammar in spec_coder.py.
- Manim API fixes: normalize_manim_code, placeholder rejection, preflight_visual_code, circle-area repair guidance in coder/fixer prompts.
- Verification: backend 15 passed (tests/test_reliability.py), compileall OK, frontend lint & production build OK (before port 3000 was stopped), backend healthy on :8000.
- Live storyboard success with fallback model (satellite topic, 4 scenes, workflow events captured); Vision QA correctly rejected visually-broken circle-area and phasor scenes.
Active
- Answering the user's visual-consistency question: research sources fetched (Manimator, PhysicsSolutionAgent, LLM2Manim, Claude Opus page) but the recommendation is not yet written back (initial research subagent task was aborted; direct fetches done instead).
Blocked
- Groq free-tier daily cap (gpt-oss-120b) — mitigated by qwen fallback, but 429/TPD errors still appear and retries add latency.
- Frontend is not running (port 3000 stopped per user request; needs restart to re-serve current UI).
- In-memory SSE event history resets on backend restart.
- No direct Anthropic key wiring yet (Opus/Sonnet only reachable via AgentRouter for vision; text models are Groq-only).
Next Move
1. Answer the visual-consistency question: recommend (a) LLM2Manim-style symbol/concept ledger — formalize a persistent per-project table (concept → shape/color) carried through _continuity_context and both coder/fixer prompts; (b) Manimator's "element layout" as explicit per-scene layout planning (already partly covered by spec compiler); (c) PhysicsSolutionAgent-style automated checks (extend vision QA beyond 3 frames or add structural code checks). Model advice: keep deterministic compiler for codegen; route planning/critique only to a stronger model (Opus via existing AgentRouter path, or Sonnet wired later) — not raw codegen — to control cost.
2. Offer to implement the concept-ledger + optionally more vision QA frames, then restart frontend on :3000 and re-verify /api/config and one live rerun.
3. (none)
Relevant Files
- backend/app/pipeline/renderer.py: normalize_manim_code, preflight_visual_code, isolated per-attempt renders — core Manim CE compatibility + placeholder guards.
- backend/app/agents/scene_graph.py: TTS entry, spec/raw codegen, fix→fresh-codegen-with-feedback loop, critique/accept/fail routing, run_scene(on_update=...), llm_with_retry TPD fallback.
- backend/app/agents/studio_graph.py: Writer/Director/Producer workflow events, structured_call TPD fallback (json_schema method required by Groq).
- backend/app/services/production_service.py: async production, _continuity_context, strict restitch + reconcile, produce_scene workflow events.
- backend/app/services/storyboard_service.py: create_project (sync) + generate_storyboard (async background, publishes events, marks failed on error).
- backend/app/pipeline/events.py: in-memory _history deque + history().
- backend/app/agents/llm.py + app/config.py: _groq, fallback_llm, fallback_model, tts_enabled, vision_max_attempts.
- backend/app/prompts/coder.py, spec_coder.py, fixer.py: few-shots, visual grammar, Manim CE repair rules.
- backend/app/main.py: /api/projects async create, /api/config, /api/projects/{id}/events/history, _active_projects locks, media 404 gating.
- backend/tests/test_reliability.py (15 tests) + tests/conftest.py; pyproject.toml (dependency-groups dev pytest).
- frontend/src/components/ui/*: shadcn primitives (button/input/textarea/select/badge/card/progress).
- frontend/src/components/smoothui/*: installed SmoothUI components (ai-* + siri-orb + chat-template).
- frontend/src/components/AgentWorkflow.tsx, SceneCard.tsx; frontend/src/app/page.tsx, src/app/project/[id]/page.tsx; frontend/src/lib/api.ts (WorkflowEvent/PublicConfig, history/config fetchers), src/lib/utils.ts; components.json.
- backend/.env: ANIMIND_GROQ_API_KEY, ANIMIND_ROUTER_API_KEY, ANIMIND_ROUTER_BASE_URL (do not print values).
- research/MANIM_FEW_SHOTS.md + research/*.pdf (Manimator, PhysicsSolutionAgent, LLM2Manim papers).
