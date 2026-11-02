"""Application configuration.

All settings come from environment variables (optionally seeded from the
repository root ``.env``). Every value has a safe default so the API boots with
no configuration at all.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../FinSight/backend/app/core/config.py -> repository root is parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]

AppEnvironment = Literal["development", "test", "staging", "production"]
LlmProvider = Literal["disabled", "openai", "anthropic", "ollama"]


class Settings(BaseSettings):
    """Typed application settings.

    Secrets are held as ``SecretStr`` so they cannot leak through ``repr()``
    or an accidental ``model_dump()`` into a log line or an error payload.
    """

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application --------------------------------------------------------
    app_name: str = "FinSight"
    app_env: AppEnvironment = "development"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- Logging ------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    # --- Data ---------------------------------------------------------------
    data_dir: Path = Path("data")

    # --- HTTP ---------------------------------------------------------------
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_bytes: int = Field(default=16_384, ge=1_024, le=1_048_576)
    max_question_length: int = Field(default=500, ge=16, le=8_000)
    max_dimensions: int = Field(default=3, ge=1, le=8)
    max_limit: int = Field(default=25, ge=1, le=200)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)

    # --- In-memory analysis store -------------------------------------------
    analysis_store_max_items: int = Field(default=100, ge=1, le=10_000)
    analysis_store_ttl_seconds: int = Field(default=3_600, ge=30)

    # --- LLM provider (optional, Phase 2) -----------------------------------
    llm_provider: LlmProvider = "disabled"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str = ""
    llm_timeout_seconds: int = Field(default=20, ge=1, le=120)
    llm_max_tokens: int = Field(default=1_200, ge=64, le=32_768)

    # --- Derived helpers ----------------------------------------------------
    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """Origins allowed to call the API from a browser."""
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())

    @property
    def resolved_data_dir(self) -> Path:
        """Absolute path to the bundled dataset directory."""
        candidate = self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir
        return candidate.resolve()

    @property
    def llm_api_key_value(self) -> str | None:
        if self.llm_api_key is None:
            return None
        value = self.llm_api_key.get_secret_value().strip()
        return value or None

    @property
    def llm_enabled(self) -> bool:
        """True only when a provider is selected *and* a key is configured.

        FinSight computes every financial figure deterministically, so an
        unconfigured LLM degrades the product rather than breaking it.
        """
        return self.llm_provider != "disabled" and self.llm_api_key_value is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()