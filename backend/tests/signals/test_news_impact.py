from decimal import Decimal

import pytest

from app.signals.news_impact import Materiality, NewsCategory, classify


@pytest.mark.parametrize(
    ("headline", "category"),
    [
        ("Apple beats estimates on record iPhone revenue", NewsCategory.EARNINGS),
        ("Acme raises full-year guidance after strong quarter", NewsCategory.GUIDANCE),
        ("Globex to acquire Initech in $5bn takeover", NewsCategory.MA),
        ("Analysts upgrade Tesla, lift price target to $400", NewsCategory.RATING_CHANGE),
        ("SEC opens probe into Hooli accounting", NewsCategory.LEGAL_REG),
        ("Nvidia unveils new AI chip at launch event", NewsCategory.PRODUCT),
        ("Fed signals another interest rate hike as inflation persists", NewsCategory.MACRO),
        ("Company names new head of European sales", NewsCategory.OTHER),
    ],
)
def test_classifies_by_keyword(headline: str, category: NewsCategory) -> None:
    assert classify(headline).category is category


def test_earnings_wins_over_rating_when_both_present() -> None:
    # Priority order: earnings is checked before rating changes.
    impact = classify("Acme beats estimates; analysts raise price target")
    assert impact.category is NewsCategory.EARNINGS
    assert "beats estimates" in impact.matched


def test_base_materiality_by_category() -> None:
    assert classify("Acme reports Q3 earnings").materiality is Materiality.HIGH
    assert classify("Analysts downgrade Acme").materiality is Materiality.MEDIUM
    assert classify("Acme launches new website").materiality is Materiality.LOW


def test_large_move_bumps_materiality_up_one_level() -> None:
    # A product headline is Low, but a confirmed 8% move makes the market's verdict Medium.
    assert classify("Acme unveils new app", price_change_pct=Decimal("8")).materiality is Materiality.MEDIUM
    # Below the threshold it stays put.
    assert classify("Acme unveils new app", price_change_pct=Decimal("2")).materiality is Materiality.LOW
    # High can't bump past High.
    assert classify("Acme Q3 earnings", price_change_pct=Decimal("-30")).materiality is Materiality.HIGH


def test_tone_comes_from_headline_words() -> None:
    assert classify("Acme surges after upgrade").tone == 1
    assert classify("Acme plunges on fraud probe").tone == -1


def test_matched_keywords_reported_for_transparency() -> None:
    impact = classify("Globex merger with Initech approved by regulators")
    assert impact.category is NewsCategory.MA
    assert "merger" in impact.matched


def test_word_boundary_avoids_false_positives() -> None:
    # Substrings must not match: "funding" contains no whole keyword, "feedback" isn't "fed".
    assert classify("Startup raises a funding round, shares feedback").category is NewsCategory.OTHER
