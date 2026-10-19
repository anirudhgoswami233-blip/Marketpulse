"""Password hashing (argon2), JWT access tokens, and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a JWT claim value, not a secret

_hasher = PasswordHasher()
# Verifying against a real hash when the user doesn't exist keeps login timing uniform.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


class InvalidToken(Exception):
    """The access token is missing, malformed, expired or signed with another key."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class TokenSigner:
    secret: str
    access_ttl: timedelta

    def create_access_token(self, user_id: int, now: datetime | None = None) -> tuple[str, datetime]:
        issued = now or datetime.now(UTC)
        expires = issued + self.access_ttl
        claims = {
            "sub": str(user_id),
            "type": ACCESS_TOKEN_TYPE,
            "iat": int(issued.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": secrets.token_hex(8),
        }
        return jwt.encode(claims, self.secret, algorithm=JWT_ALGORITHM), expires

    def decode_access_token(self, token: str) -> int:
        try:
            claims = jwt.decode(
                token, self.secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]}
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken(type(exc).__name__) from exc
        if claims.get("type") != ACCESS_TOKEN_TYPE:
            raise InvalidToken("wrong token type")
        try:
            return int(claims["sub"])
        except (TypeError, ValueError) as exc:
            raise InvalidToken("bad subject") from exc


def build_signer(settings: Settings) -> TokenSigner:
    if settings.jwt_secret is not None and settings.jwt_secret.get_secret_value():
        secret = settings.jwt_secret.get_secret_value()
    elif settings.env == "dev":
        # Dev convenience only: tokens stop working when the server restarts.
        logger.warning("JWT_SECRET is not set; using a random per-process secret (dev only)")
        secret = secrets.token_urlsafe(48)
    else:
        raise RuntimeError("JWT_SECRET must be set outside development")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters")
    return TokenSigner(secret=secret, access_ttl=timedelta(seconds=settings.access_token_ttl_s))


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    # Refresh tokens are high-entropy random strings, so a fast hash is appropriate (no salt needed).
    return hashlib.sha256(token.encode()).hexdigest()
