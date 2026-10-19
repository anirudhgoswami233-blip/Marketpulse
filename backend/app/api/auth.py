from fastapi import APIRouter, Request, Response, status

from app.api.deps import ContainerDep, CurrentUser, SessionDep
from app.core.config import Settings
from app.core.errors import AppError, Unauthorized
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut, UserUpdate
from app.services import auth_service
from app.services.auth_service import IssuedSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "mp_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def to_user_out(user: User) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


def _set_refresh_cookie(response: Response, settings: Settings, issued: IssuedSession) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _token_out(issued: IssuedSession) -> TokenOut:
    return TokenOut(
        access_token=issued.access_token, expires_at=issued.access_expires_at, user=to_user_out(issued.user)
    )


def _check_origin(request: Request, settings: Settings) -> None:
    """Cookie-authenticated endpoints only accept requests from our own frontend (CSRF defence in depth)."""
    origin = request.headers.get("origin")
    if origin is not None and not settings.origin_allowed(origin):
        raise AppError("Request origin not allowed.", code="bad_origin", status=403)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn, response: Response, container: ContainerDep, session: SessionDep
) -> TokenOut:
    settings = container.settings
    user = await auth_service.register(
        session, settings, body.email, body.password, body.display_name, body.timezone
    )
    issued = await auth_service.issue_session(session, container.signer, settings, user)
    await session.commit()
    _set_refresh_cookie(response, settings, issued)
    return _token_out(issued)


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn, request: Request, response: Response, container: ContainerDep, session: SessionDep
) -> TokenOut:
    settings = container.settings
    client = request.client.host if request.client else "unknown"
    user = await auth_service.authenticate(
        session, container.cache, settings, body.email, body.password, client
    )
    issued = await auth_service.issue_session(session, container.signer, settings, user)
    await session.commit()
    _set_refresh_cookie(response, settings, issued)
    return _token_out(issued)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request, response: Response, container: ContainerDep, session: SessionDep
) -> TokenOut:
    _check_origin(request, container.settings)
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthorized("Please sign in to continue.", code="not_authenticated")
    issued = await auth_service.rotate_session(session, container.signer, container.settings, token)
    await session.commit()
    _set_refresh_cookie(response, container.settings, issued)
    return _token_out(issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, container: ContainerDep, session: SessionDep) -> None:
    _check_origin(request, container.settings)
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await auth_service.revoke(session, token)
        await session.commit()
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return to_user_out(user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: UserUpdate, user: CurrentUser, session: SessionDep) -> UserOut:
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.timezone is not None:
        auth_service.validate_timezone(body.timezone)
        user.timezone = body.timezone
    if body.brief_time is not None:
        user.brief_time = body.brief_time.replace(second=0, microsecond=0, tzinfo=None)
    if body.brief_email_enabled is not None:
        user.brief_email_enabled = body.brief_email_enabled
    await session.commit()
    return to_user_out(user)
