from pydantic import BaseModel


class ProviderStatus(BaseModel):
    name: str
    configured: bool


class LimiterStatus(BaseModel):
    name: str
    used_in_window: int
    limit_per_window: int
    window_s: float
    used_today: int | None
    daily_limit: int | None


class SystemStatus(BaseModel):
    cache_backend: str
    providers: list[ProviderStatus]
    limiters: list[LimiterStatus]
