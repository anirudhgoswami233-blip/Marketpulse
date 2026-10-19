import pytest

from app.core.config import Settings, normalize_database_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # Neon's connection string
        (
            "postgresql://u:p%40ss@ep-cool-1.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p%40ss@ep-cool-1.eu-central-1.aws.neon.tech/neondb?ssl=require",
        ),
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgresql+asyncpg://u:p@host/db?ssl=require", "postgresql+asyncpg://u:p@host/db?ssl=require"),
        ("sqlite+aiosqlite:///./marketpulse.db", "sqlite+aiosqlite:///./marketpulse.db"),
    ],
)
def test_database_urls_from_hosted_postgres_work_with_asyncpg(url: str, expected: str) -> None:
    assert normalize_database_url(url) == expected
    assert Settings(_env_file=None, database_url=url).database_url == expected


def test_origin_allowed_checks_the_list_and_the_optional_regex() -> None:
    settings = Settings(
        _env_file=None,
        cors_origins=["https://marketpulse.vercel.app"],
        cors_origin_regex=r"https://marketpulse-[a-z0-9-]+-team\.vercel\.app",
    )
    assert settings.origin_allowed("https://marketpulse.vercel.app")
    assert settings.origin_allowed("https://marketpulse-git-main-team.vercel.app")
    assert not settings.origin_allowed("https://marketpulse-x-team.vercel.app.evil.com")
    assert not settings.origin_allowed("https://evil.vercel.app")
    assert not Settings(_env_file=None).origin_allowed("https://evil.vercel.app")
