from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import Unauthorized
from app.core.security import InvalidToken
from app.models import Symbol, User
from app.services.search_service import resolve_symbol

SYMBOL_PATTERN = r"^[A-Za-z0-9.:_\-^]{1,32}$"


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


async def get_session(container: Annotated[Container, Depends(get_container)]) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


ContainerDep = Annotated[Container, Depends(get_container)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_symbol(
    session: SessionDep, symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN)], exchange: str | None = None
) -> Symbol:
    return await resolve_symbol(session, symbol, exchange)


SymbolDep = Annotated[Symbol, Depends(get_symbol)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    container: ContainerDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Please sign in to continue.", code="not_authenticated")
    try:
        user_id = container.signer.decode_access_token(credentials.credentials)
    except InvalidToken as exc:
        # The frontend refreshes on this code and retries once.
        raise Unauthorized("Your session has expired.", code="token_expired") from exc
    user = await session.get(User, user_id)
    if user is None:
        raise Unauthorized("Please sign in to continue.", code="not_authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
