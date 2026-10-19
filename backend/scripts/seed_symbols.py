"""Seed the exchange list and symbol directory from Finnhub. Run once, then weekly via the refresh job.

Usage (from backend/, after `alembic upgrade head`):
    .venv/Scripts/python scripts/seed_symbols.py                 # US stocks + OANDA forex pairs
    .venv/Scripts/python scripts/seed_symbols.py --exchange US --exchange L
    .venv/Scripts/python scripts/seed_symbols.py --extras-only   # just the extra forex pairs, no API calls

Exchanges that the Finnhub free tier doesn't serve (see docs/finnhub-endpoints.md) are skipped with a warning.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.exc import OperationalError, ProgrammingError

from app.container import build_container
from app.core.config import get_settings
from app.core.errors import ProviderError, ProviderUnavailable
from app.core.logging import configure_logging
from app.services import symbol_directory

logger = logging.getLogger("seed_symbols")


async def seed(exchanges: list[str], include_forex: bool, extras_only: bool = False) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    if settings.finnhub_api_key is None and not extras_only:
        logger.error("FINNHUB_API_KEY is not set in backend/.env")
        return 1

    container = build_container(settings)
    provider = container.providers.reference
    failures = 0
    try:
        async with container.session_factory() as session:
            try:
                count = await symbol_directory.upsert_exchanges(
                    session, symbol_directory.load_exchange_rows()
                )
                await session.commit()
            except (OperationalError, ProgrammingError):
                logger.error("Database tables are missing. Run `alembic upgrade head` first.")
                return 1
            logger.info("Upserted %d exchanges", count)

            for code in [] if extras_only else exchanges:
                try:
                    fetched = await provider.list_symbols(code)
                except ProviderUnavailable:
                    logger.warning("Skipping %s: symbol list not available on the Finnhub free tier", code)
                    continue
                except ProviderError as exc:
                    logger.error("Failed to fetch symbols for %s: %s", code, exc)
                    failures += 1
                    continue
                count = await symbol_directory.upsert_symbols(session, code, fetched.data)
                await session.commit()
                logger.info("Upserted %d symbols for %s", count, code)

            if include_forex:
                extra = symbol_directory.extra_pair_records()
                count = await symbol_directory.upsert_symbols(
                    session, symbol_directory.EXTRA_FX_EXCHANGE, extra
                )
                await session.commit()
                logger.info("Upserted %d extra forex pairs (no API call)", count)
                if extras_only:
                    return 0
                try:
                    forex = await provider.list_forex_symbols("oanda")
                except ProviderError as exc:
                    logger.error("Failed to fetch forex symbols: %s", exc)
                    failures += 1
                else:
                    records = symbol_directory.forex_to_records(forex.data)
                    count = await symbol_directory.upsert_symbols(
                        session, symbol_directory.FOREX_EXCHANGE, records
                    )
                    await session.commit()
                    logger.info("Upserted %d forex pairs", count)
    finally:
        await container.close()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--exchange", action="append", help="Finnhub exchange code (repeatable). Default: US")
    parser.add_argument("--no-forex", action="store_true", help="Skip OANDA forex pairs")
    parser.add_argument(
        "--extras-only",
        action="store_true",
        help="Only upsert exchanges and the extra forex pairs from app/data/forex.json (no API calls)",
    )
    args = parser.parse_args()
    return asyncio.run(
        seed(args.exchange or ["US"], include_forex=not args.no_forex, extras_only=args.extras_only)
    )


if __name__ == "__main__":
    sys.exit(main())
