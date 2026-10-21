"""Application configuration.

Centralised, overridable settings for the multi-agent ticket system.
Every value can be overridden with an environment variable prefixed AGENT_.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(f"AGENT_{key}", os.environ.get(key, default))


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(f"AGENT_{key}", os.environ.get(key))
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(f"AGENT_{key}", os.environ.get(key))
    return int(raw) if raw not in (None, "") else default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(f"AGENT_{key}", os.environ.get(key))
    return float(raw) if raw not in (None, "") else default


@dataclass
class Settings:
    # --- Service ---
    app_name: str = "Multi-Agent Ticket Collaboration System"
    environment: str = _env("ENVIRONMENT", "development") or "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = _env_bool("DEBUG", False)
    host: str = _env("HOST", "0.0.0.0") or "0.0.0.0"
    port: int = _env_int("PORT", 8000)

    # --- LLM (agnes-3-flash) ---
    llm_provider: str = _env("LLM_PROVIDER", "agnes") or "agnes"
    llm_model: str = _env("LLM_MODEL", "agnes-3-flash") or "agnes-3-flash"
    llm_api_key: str = _env("LLM_API_KEY", "") or ""
    llm_base_url: str = _env(
        "LLM_BASE_URL",
        "https://api.sapiens.ai/v1",
    ) or "https://api.sapiens.ai/v1"
    llm_timeout_s: float = _env_float("LLM_TIMEOUT_S", 30.0)
    llm_max_retries: int = _env_int("LLM_MAX_RETRIES", 3)
    llm_temperature: float = _env_float("LLM_TEMPERATURE", 0.2)
    llm_enabled: bool = _env_bool("LLM_ENABLED", True)

    # --- Database ---
    sqlite_path: str = _env("SQLITE_PATH", "data/tickets.sqlite3") or "data/tickets.sqlite3"
    use_redis: bool = _env_bool("USE_REDIS", False)
    redis_url: str = _env("REDIS_URL", "redis://127.0.0.1:6379/0") or "redis://127.0.0.1:6379/0"

    # --- Security ---
    jwt_secret: str = _env(
        "JWT_SECRET",
        "local-dev-only-change-before-deployment-32b",
    ) or "local-dev-only-change-before-deployment-32b"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = _env_int("JWT_EXPIRES_MINUTES", 720)
    cors_origins: list = field(default_factory=lambda: ["*"])

    # --- SLA (seconds per department before auto-escalation) ---
    sla_seconds: dict = field(default_factory=lambda: {
        "IT": 30,
        "HR": 60,
        "PROCUREMENT": 120,
        "FINANCE": 90,
        "OTHER": 120,
    })


settings = Settings()
