from decimal import Decimal
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
    # Background jobs are paced by the limiter, so they may queue much longer than user requests.
    limiter_background_max_wait_s: float = 600.0

    # Scheduled jobs and the shared Finnhub WebSocket (both off in tests).
    enable_background_jobs: bool = True
    enable_streaming: bool = True
    # Finnhub's free WebSocket allows 50 symbols per connection.
    finnhub_ws_max_symbols: int = 50
    sse_max_symbols_per_client: int = 30
    overview_refresh_open_s: int = 300
    overview_refresh_closed_s: int = 1800

    # Auth: short-lived JWT access tokens, rotating opaque refresh tokens in an httpOnly cookie.
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_days: int = 30
    # A token rotated this recently is a benign race (two tabs refreshing at once), not a stolen token.
    refresh_reuse_grace_s: int = 30
    # Set true behind HTTPS in production so the refresh cookie is never sent over plain HTTP.
    cookie_secure: bool = False
    login_max_failures: int = 5
    login_lockout_s: int = 15 * 60

    # Paper trading
    paper_starting_cash: Decimal = Decimal("100000")
    paper_base_currency: str = "USD"
    max_watchlists_per_user: int = 10
    max_watchlist_items: int = 50

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
