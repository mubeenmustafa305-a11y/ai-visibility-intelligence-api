"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _resolve_database_url(url: str) -> str:
    """Make relative SQLite paths absolute to the project root."""
    if not url.startswith("sqlite:///"):
        return url

    path = url.removeprefix("sqlite:///")
    if path == ":memory:" or path.startswith("/"):
        return url

    # Windows absolute paths look like sqlite:///C:/... after the prefix.
    if len(path) >= 2 and path[1] == ":":
        return url

    return f"sqlite:///{(BASE_DIR / path).as_posix()}"


def _default_database_url() -> str:
    return f"sqlite:///{(BASE_DIR / 'dev.db').as_posix()}"


class Config:
    """Base Flask configuration."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI: str = _resolve_database_url(
        os.getenv("DATABASE_URL", _default_database_url())
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    JSON_SORT_KEYS: bool = False

    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    DATAFORSEO_LOGIN: str | None = os.getenv("DATAFORSEO_LOGIN")
    DATAFORSEO_PASSWORD: str | None = os.getenv("DATAFORSEO_PASSWORD")
    DATAFORSEO_BASE_URL: str = os.getenv(
        "DATAFORSEO_BASE_URL",
        "https://api.dataforseo.com",
    )
    DATAFORSEO_LOCATION_CODE: int = int(os.getenv("DATAFORSEO_LOCATION_CODE", "2840"))
    DATAFORSEO_LANGUAGE_CODE: str = os.getenv("DATAFORSEO_LANGUAGE_CODE", "en")
    DATAFORSEO_TIMEOUT_SECONDS: float = float(
        os.getenv("DATAFORSEO_TIMEOUT_SECONDS", "60")
    )
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "1"))


class DevelopmentConfig(Config):
    DEBUG: bool = True


class TestingConfig(Config):
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"


class ProductionConfig(Config):
    DEBUG: bool = False


CONFIG_MAP: dict[str, type[Config]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    """Resolve config class from FLASK_ENV or an explicit name."""
    env = (name or os.getenv("FLASK_ENV", "development")).lower()
    return CONFIG_MAP.get(env, DevelopmentConfig)
