"""Runtime configuration. Secrets stay in the environment and are never logged."""

import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
# llama3-70b-8192 and llama-3.3-70b-versatile are no longer on Groq's developer tier.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
# Empty string omits reasoning_effort. The default keeps gpt-oss answers short enough to return.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low").strip()
# eleven_monolingual_v1 was removed. eleven_flash_v2_5 is the current default.
ELEVENLABS_MODEL_ID = (os.getenv("ELEVENLABS_MODEL_ID") or "eleven_flash_v2_5").strip()
ELEVENLABS_VOICE_ID = (os.getenv("ELEVENLABS_VOICE_ID") or "pNInz6obpgDQGcFmaJgB").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")


def ai_stub_enabled() -> bool:
    """Read on each call so tests can enable the stub before importing the app."""
    return _flag("AI_STUB")


def missing_ai_keys() -> list:
    if ai_stub_enabled():
        return []
    missing = []
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not ELEVENLABS_API_KEY:
        missing.append("ELEVENLABS_API_KEY")
    return missing
