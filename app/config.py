"""Application settings, loaded from the environment (and an optional .env file)."""

import re
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Valid characters for an HTTP header name (RFC 7230 token).
HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Healthcare Voice Agent API"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True

    host: str = "127.0.0.1"
    port: int = 8000

    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Async driver for the app; Alembic reuses this URL via
    # app/Repository/migrations/env.py.
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/healthcare_voice_agent"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10


    # --- Logging ------------------------------------------------------
    log_level: str = "INFO"
    #: Log full webhook request/response bodies. These contain patient names and
    #: dates of birth (PHI), so keep this off anywhere real calls land.
    log_payloads: bool = False

    # --- Vapi ---------------------------------------------------------
    # Shared secret checked against the header Vapi sends. Set the same value
    # under Phone Number -> Authorization -> HTTP Headers in the dashboard.
    vapi_secret: str = ""
    vapi_secret_header: str = "x-vapi-secret"

    # Public HTTPS base URL Vapi can reach (ngrok in development). Used to build
    # the tool server URL handed back with the assistant config.
    public_base_url: str = "http://localhost:8000"

    # --- LLM ----------------------------------------------------------
    # Used to summarise call transcripts. Summaries are skipped, not fatal,
    # when this is unset.
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 400
    #: Transcripts longer than this are truncated before summarising.
    llm_max_transcript_chars: int = 24000

    # Spoken in the greeting and used in the agent's self-description.
    clinic_name: str = "Bilal's Clinic"

    vapi_model_provider: str = "openai"
    vapi_model: str = "gpt-4o"
    vapi_voice_provider: str = "vapi"
    vapi_voice_id: str = "Elliot"


    @field_validator("vapi_secret_header")
    @classmethod
    def _validate_header_name(cls, value: str) -> str:
        """Catches a secret pasted into the header-name slot.

        The two settings sit next to each other and are easy to transpose; a
        header name with spaces in it just 401s every request with no clue why,
        so fail at startup instead.
        """
        if not HEADER_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                f"VAPI_SECRET_HEADER must be an HTTP header name such as "
                f"'x-vapi-secret', not a secret value (got {value!r})"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()
