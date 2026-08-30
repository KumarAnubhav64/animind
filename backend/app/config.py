from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ANIMIND_",
        extra="ignore",  # tolerate unrelated ANIMIND_* env vars (e.g. provider keys)
    )

    groq_api_key: str = ""
    groq_api_key_backup: str = ""  # second Groq key used after primary-key retries are exhausted

    planner_model: str = "openai/gpt-oss-120b"  # only model that handles nested json_schema reliably
    coder_model: str = "openai/gpt-oss-120b"  # strongest codegen
    fixer_model: str = "openai/gpt-oss-20b"  # plain-text repair; keeps 120b TPM budget for codegen
    fallback_model: str = "qwen/qwen3.8-27b"  # use when the primary model hits a daily cap
    premium_model: str | None = None  # optional router model for hard repair cases
    premium_repair_enabled: bool = False
    premium_repair_max_calls: int = 1
    math_expert_enabled: bool = True
    math_expert_max_attempts: int = 1
    math_expert_model: str | None = None  # stronger router model for the subject-expert gate; None = fixer model
    langsmith_tracing: bool = False
    tts_model: str = "canopylabs/orpheus-v1-english"
    tts_voice: str = "autumn"  # autumn|diana|hannah|austin|daniel|troy

    max_scene_retries: int = 5
    max_parallel_scenes: int = 2  # free-tier TPM: 120b codegen is ~5k tokens/call
    codegen_mode: str = "spec"  # spec (declarative, compiled) | raw (LLM writes Manim)
    tts_enabled: bool = True
    vision_model: str = "claude-opus-4-8"
    vision_model_fallback: str | None = "qwen/qwen3.6-27b"  # Groq free-tier vision model (text+image)
    vision_model_fallback_vision_capable: bool = True  # qwen3.6-27b is multimodal; it may gate visual QA
    vision_critique: bool = True  # screenshot-based visual QA before accepting a scene
    vision_max_frames: int = 3
    vision_max_frames_fallback: int = 2  # free-tier Groq vision: fixed ~2740 tokens/image, 8K TPM -> 2 frames
    vision_frame_width: int = 480
    vision_max_attempts: int = 3  # inspect the original plus up to two repaired candidates
    router_api_key: str | None = None  # AgentRouter (OpenAI-compatible)
    router_base_url: str = "https://agentrouter.org/v1"
    sequential_scenes: bool = True  # roll context forward scene-to-scene (quality > speed)
    max_scenes: int = 4
    max_narration_seconds: int = 35
    max_storyboard_revisions: int = 2

    research_enabled: bool = True  # web-search the topic before the Writer plans
    research_results_per_query: int = 4

    media_dir: str = "media"
    database_url: str = "animind.db"

    cors_origins: list[str] = ["http://localhost:3000"]

@lru_cache
def get_settings() -> Settings:
    return Settings()
