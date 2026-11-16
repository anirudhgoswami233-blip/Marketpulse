"""Every brief email must carry an unsubscribe link and a postal address, and the link must work."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.models
from app.container import Container
from app.core.security import InvalidToken
from app.main import create_app
from app.services import auth_service, email_service
from tests.api_helpers import file_db, make_settings, prepare
from tests.fakes import FakeProvider

ADDRESS = "221B Example Street, Springfield, EX 00000"
MAIL = {
    "smtp_host": "smtp.example.test",
    "smtp_from": "briefs@example.test",
    "public_app_url": "https://app.example.test/",
    "mail_postal_address": ADDRESS,
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(database_url=file_db(tmp_path), **MAIL))) as test_client:
        container: Container = test_client.app.state.container  # type: ignore[attr-defined]
        assert test_client.portal is not None
        test_client.portal.call(prepare, container, FakeProvider())
        yield test_client


@pytest.mark.parametrize("missing", ["smtp_host", "smtp_from", "public_app_url", "mail_postal_address"])
def test_email_is_off_unless_link_and_address_can_be_included(missing: str) -> None:
    assert email_service.email_configured(make_settings(**MAIL))
    assert not email_service.email_configured(make_settings(**{**MAIL, missing: " "}))


async def test_nothing_is_sent_without_a_postal_address() -> None:
    settings = make_settings(**{**MAIL, "mail_postal_address": ""})
    assert await email_service.send_email(settings, "a@example.test", "Hi", "Body", "https://x/u") is False


def test_message_has_unsubscribe_link_headers_and_postal_address() -> None:
    settings = make_settings(**MAIL)
    link = email_service.unsubscribe_url(settings, "7.abc")
    assert link == "https://app.example.test/api/v1/email/unsubscribe?token=7.abc"

    message = email_service.build_message(settings, "a@example.test", "Your brief", "# Brief\n\nBody.", link)

    body = message.get_content()
    assert body.startswith("# Brief")
    assert f"Unsubscribe: {link}" in body
    assert ADDRESS in body
    assert message["List-Unsubscribe"] == f"<{link}>"
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_unsubscribe_tokens_are_signed_per_user(client: TestClient) -> None:
    signer = client.app.state.container.signer  # type: ignore[attr-defined]
    token = signer.unsubscribe_token(42)
    assert signer.verify_unsubscribe_token(token) == 42
    for forged in ("43." + token.split(".")[1], "42.deadbeef", "42", "abc.def", ""):
        with pytest.raises(InvalidToken):
            signer.verify_unsubscribe_token(forged)


def test_unsubscribe_link_turns_brief_emails_off_without_signing_in(client: TestClient) -> None:
    container: Container = client.app.state.container  # type: ignore[attr-defined]

    async def make_subscriber() -> int:
        async with container.session_factory() as session:
            user = await auth_service.register(
                session, container.settings, "sub@example.com", "password123", "Sub", "UTC", date(1990, 5, 17)
            )
            user.brief_email_enabled = True
            await session.commit()
            return user.id

    async def emails_enabled(user_id: int) -> bool:
        async with container.session_factory() as session:
            user = await session.get(app.models.User, user_id)
            assert user is not None
            return user.brief_email_enabled

    assert client.portal is not None
    user_id = client.portal.call(make_subscriber)
    url = "/api/v1/email/unsubscribe"
    token = container.signer.unsubscribe_token(user_id)

    # Opening the link (as a mail scanner would) asks for confirmation and changes nothing.
    page = client.get(url, params={"token": token})
    assert page.status_code == 200 and '<form method="post">' in page.text
    assert client.portal.call(emails_enabled, user_id) is True

    # The button, or a mail client's one-click POST, unsubscribes. Repeating it is harmless.
    for _ in range(2):
        done = client.post(url, params={"token": token})
        assert done.status_code == 200 and "unsubscribed" in done.text
    assert client.portal.call(emails_enabled, user_id) is False


def test_forged_unsubscribe_link_is_rejected(client: TestClient) -> None:
    for method in (client.get, client.post):
        response = method("/api/v1/email/unsubscribe", params={"token": "1.forged"})
        assert response.status_code == 400 and "valid" in response.text
