"""Unsubscribe from Daily Brief emails without signing in.

Every brief email carries a signed link here (and the List-Unsubscribe headers). Opening the link shows a
confirmation button rather than unsubscribing on GET, because mail scanners prefetch links; mail clients'
one-click unsubscribe sends the POST directly.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.api.deps import ContainerDep, SessionDep
from app.core.security import InvalidToken
from app.models import User

router = APIRouter(prefix="/api/v1/email", tags=["email"])

TokenParam = Annotated[str, Query(min_length=1, max_length=200)]


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{title} · MarketPulse</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem;"
        "line-height:1.5;color:#0d0f12;background:#f6f7f8}h1{font-size:1.25rem}"
        "button{font:inherit;padding:.5rem 1rem;border:1px solid #1a56b8;border-radius:4px;"
        "background:#1a56b8;color:#fff;cursor:pointer}a{color:#1a56b8}"
        "@media(prefers-color-scheme:dark){body{color:#eceef1;background:#0c0d0f}a{color:#74a9f5}}"
        "</style></head>"
        f"<body><h1>{title}</h1>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=status)


def _invalid() -> HTMLResponse:
    return _page(
        "This unsubscribe link isn't valid",
        "<p>The link may be incomplete. You can turn brief emails off under "
        "<strong>Brief &rarr; Brief settings</strong> after signing in.</p>",
        status=400,
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page(token: TokenParam, container: ContainerDep) -> HTMLResponse:
    try:
        container.signer.verify_unsubscribe_token(token)
    except InvalidToken:
        return _invalid()
    return _page(
        "Unsubscribe from Daily Brief emails?",
        "<p>You'll stop receiving the Daily Market Brief by email. Your account and your briefs on the "
        'site are not affected.</p><form method="post"><button type="submit">Unsubscribe</button></form>',
    )


@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: TokenParam, container: ContainerDep, session: SessionDep) -> HTMLResponse:
    try:
        user_id = container.signer.verify_unsubscribe_token(token)
    except InvalidToken:
        return _invalid()
    user = await session.get(User, user_id)
    # An account that no longer exists has nothing left to email: report success either way.
    if user is not None and user.brief_email_enabled:
        user.brief_email_enabled = False
        await session.commit()
    return _page(
        "You're unsubscribed",
        "<p>We won't send you the Daily Market Brief by email any more. You can turn it back on any time "
        "under <strong>Brief &rarr; Brief settings</strong>.</p>",
    )
