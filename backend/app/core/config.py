from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    finnhub_api_key: SecretStr | None = None
    twelvedata_api_key: SecretStr | None = None
    fred_api_key: SecretStr | None = None
    llm_api_key: SecretStr | None = None

    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'marketpulse.db').as_posix()}"
    # Empty means: use the in-process cache and rate limiter (single-process dev only).
    redis_url: str = ""
    jwt_secret: SecretStr | None = None

    # Rate limits sit below each vendor's published free-tier ceiling to leave headroom.
    finnhub_calls_per_minute: int = 50
    twelvedata_calls_per_minute: int = 7
    twelvedata_calls_per_day: int = 750
    fred_calls_per_minute: int = 100
    # Share of each per-minute budget that background jobs may use; the rest is kept for user requests.
    background_budget_share: float = 0.7
    # How long a caller waits in the limiter queue before giving up and falling back to stale data.
    limiter_max_wait_s: float = 30.0

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = ""

    def secret_values(self) -> list[str]:
        """Every configured secret, for log redaction."""
        secrets = [
            self.finnhub_api_key,
            self.twelvedata_api_key,
            self.fred_api_key,
            self.llm_api_key,
            self.jwt_secret,
            self.smtp_password,
        ]
        return [s.get_secret_value() for s in secrets if s and s.get_secret_value()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
