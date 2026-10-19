from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    InvalidToken,
    TokenSigner,
    build_signer,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from tests.api_helpers import TEST_JWT_SECRET, make_settings

SIGNER = TokenSigner(secret=TEST_JWT_SECRET, access_ttl=timedelta(minutes=15))


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2")
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_access_token_roundtrip() -> None:
    token, expires = SIGNER.create_access_token(42)
    assert SIGNER.decode_access_token(token) == 42
    assert expires > datetime.now(UTC)


def test_expired_token_is_rejected() -> None:
    token, _ = SIGNER.create_access_token(1, now=datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(InvalidToken):
        SIGNER.decode_access_token(token)


def test_token_signed_with_another_key_is_rejected() -> None:
    other = TokenSigner(secret="another-secret-that-is-long-enough-9876543", access_ttl=timedelta(minutes=15))
    token, _ = other.create_access_token(1)
    with pytest.raises(InvalidToken):
        SIGNER.decode_access_token(token)


def test_unsigned_and_wrong_type_tokens_are_rejected() -> None:
    none_alg = jwt.encode({"sub": "1", "exp": 9999999999, "type": "access"}, key="", algorithm="none")
    with pytest.raises(InvalidToken):
        SIGNER.decode_access_token(none_alg)
    refresh_like = jwt.encode({"sub": "1", "exp": 9999999999, "type": "refresh"}, TEST_JWT_SECRET, "HS256")
    with pytest.raises(InvalidToken):
        SIGNER.decode_access_token(refresh_like)


def test_refresh_tokens_are_random_and_hashed() -> None:
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 60
    assert hash_refresh_token(a) == hash_refresh_token(a) != a


def test_signer_requires_a_strong_secret_outside_dev() -> None:
    with pytest.raises(RuntimeError):
        build_signer(make_settings(env="prod", jwt_secret=None))
    with pytest.raises(RuntimeError):
        build_signer(make_settings(jwt_secret="short"))
    assert build_signer(make_settings(env="dev", jwt_secret=None)).secret  # dev falls back to a random secret
