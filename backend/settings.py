"""Runtime configuration. Secrets stay in the environment and are never logged."""

import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
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
