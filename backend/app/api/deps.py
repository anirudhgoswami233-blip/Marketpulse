from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.models import Symbol
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
