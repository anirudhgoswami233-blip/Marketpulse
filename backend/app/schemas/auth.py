from datetime import datetime, time

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    display_name: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="UTC", max_length=64)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    timezone: str
    base_currency: str
    brief_time: time
    brief_email_enabled: bool
    created_at: datetime


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)
    brief_time: time | None = None
    brief_email_enabled: bool | None = None


class TokenOut(BaseModel):
    """The refresh token is never in the body: it travels only in an httpOnly cookie."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    user: UserOut
