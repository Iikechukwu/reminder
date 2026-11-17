"""Settings, read from environment variables (and a local .env file).

Field names map to env vars case-insensitively: `database_url` <- DATABASE_URL.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Neon: pooled URL for the API, direct URL for the worker and migrations.
    database_url: str
    database_url_direct: str

    # Shared secret for HMAC-SHA256 webhook signatures.
    webhook_secret: str

    # Reminder is scheduled this many hours before the booking starts.
    reminder_lead_hours: int = 24

    # Job retry policy.
    max_attempts: int = 5
    backoff_base_seconds: float = 30.0
    backoff_cap_seconds: float = 3600.0
    # A job stuck in 'running' longer than this is assumed to belong to a
    # crashed worker and may be claimed again.
    visibility_timeout_seconds: int = 300

    worker_poll_interval_seconds: float = 2.0

    # Per-API-key fixed-window rate limit.
    rate_limit_per_minute: int = 60

    log_level: str = "INFO"

    # Mock email provider: probability (0..1) that a send fails. For demos.
    mock_email_fail_rate: float = 0.0

    # Reminder text drafting (M6). "fake_ok" | "fake_slow" | "fake_garbage" | "off"
    llm_mode: str = "off"
    llm_timeout_seconds: float = 3.0
