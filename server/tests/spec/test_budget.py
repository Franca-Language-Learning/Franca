"""Tests for the spending limiter (spec/ai_budget.py). The model adapter has to pass the same cases."""

import sqlite3
from pathlib import Path

import pytest

from franca.ai.budget import (
    FALLBACK,
    FIRST_ESTIMATE,
    MICRO,
    Budget,
    Price,
    Usage,
    cost,
    decide,
    estimate,
    month_estimate,
    new_alerts,
    tier_for,
)

SONNET = Price("claude-sonnet-5-5", 0, 2_000_000, 10_000_000, 2_500_000, 4_000_000, 100_000)
HAIKU = Price("claude-haiku-5-5", 0, 100_000, 500_000, 125_000, 200_000, 10_000)
HAIKU_LONG = Price("claude-haiku-5-5", 100_001, 500_000, 2_500_000, 625_000, 1_000_000, 50_000)
PRICES = [SONNET, HAIKU, HAIKU_LONG]
LEARNING = Budget(monthly_limit=40 * MICRO, learner_daily_limit=3 * MICRO)
CONTENT = Budget(monthly_limit=60 * MICRO, learner_daily_limit=None)


def test_cost_matches_the_database_view():
    assert cost(Usage(input=1000, cache_read=3000, output=150), SONNET) == 3800


def test_haiku_price_tier_follows_prompt_size():
    assert tier_for(PRICES, "claude-haiku-5-5", 100_000) is HAIKU
    assert tier_for(PRICES, "claude-haiku-5-5", 100_001) is HAIKU_LONG
    # cache reads count towards the prompt size
    assert tier_for(PRICES, "claude-haiku-5-5", Usage(input=1000, cache_read=100_000).prompt) is HAIKU_LONG


def test_estimate_prices_the_prompt_at_the_highest_prompt_rate():
    # the 1-hour cache write (4 dollars per million) is the highest prompt rate for Sonnet
    assert estimate(PRICES, "claude-sonnet-5-5", 4000, 1000) == 4000 * 4 + 1000 * 10


@pytest.mark.parametrize(
    "usage",
    [
        Usage(input=100_000, output=1000),
        Usage(cache_write_1h=100_000, output=1000),
        Usage(cache_write_5m=60_000, cache_read=40_000, output=1000),
        Usage(input=1, cache_write_1h=99_999, output=0),
    ],
)
def test_real_cost_never_passes_the_estimate(usage):
    assert cost(usage, tier_for(PRICES, "claude-sonnet-5-5", usage.prompt)) <= estimate(PRICES, "claude-sonnet-5-5", usage.prompt, 1000)


def test_a_model_without_a_price_is_refused():
    assert decide(estimate(PRICES, "mistral-large", 1000, 100), 0, LEARNING).reason == "no_price"


def test_monthly_limit():
    assert decide(10_000, 39_990_000, LEARNING).allowed
    assert decide(10_001, 39_990_000, LEARNING).reason == "monthly_limit"


def test_daily_limit_per_learner():
    assert decide(10_000, 0, LEARNING, learner_day_spent=2_990_000).allowed
    assert decide(10_001, 0, LEARNING, learner_day_spent=2_990_000).reason == "learner_daily_limit"
    assert decide(10_001, 0, CONTENT, learner_day_spent=99 * MICRO).allowed  # content jobs have no daily limit


def test_alerts_are_sent_once_and_caught_up():
    assert new_alerts(19 * MICRO, LEARNING, set()) == []
    assert new_alerts(20 * MICRO, LEARNING, set()) == ["first_warning"]
    assert new_alerts(33 * MICRO, LEARNING, {"first_warning"}) == ["second_warning"]
    assert new_alerts(40 * MICRO, LEARNING, set()) == ["first_warning", "second_warning", "limit_reached"]
    # spending stops just under the limit, so the first refusal sends the last message
    assert new_alerts(39_990_000, LEARNING, {"first_warning", "second_warning"}, refused=True) == ["limit_reached"]
    assert new_alerts(39_990_000, LEARNING, {"first_warning", "second_warning", "limit_reached"}, refused=True) == []


def test_every_purpose_in_the_database_has_a_fallback():
    import re

    schema = (Path(__file__).resolve().parents[3] / "contracts" / "db" / "schema.sql").read_text()
    table = schema[schema.index("CREATE TABLE ai_request (") :]
    check = re.search(r"purpose\s+TEXT\s+NOT NULL CHECK \(purpose IN \(([^)]*)\)", table).group(1)
    purposes = set(re.findall(r"'([a-z_]+)'", check))
    assert len(purposes) >= 8 and purposes <= set(FALLBACK)


def test_first_limit_is_about_twice_the_estimate():
    est = month_estimate(PRICES, FIRST_ESTIMATE, learners=2)
    assert 18 * MICRO < est < 20 * MICRO
    assert 1.8 < LEARNING.monthly_limit / est < 2.3


def test_seeded_prices_and_limits_match_this_spec():
    db = sqlite3.connect(":memory:")
    root = Path(__file__).resolve().parents[3] / "contracts" / "db"
    db.executescript((root / "schema.sql").read_text())
    db.executescript((root / "seed.sql").read_text())
    rows = db.execute(
        "SELECT model, min_prompt_tokens, input, output, cache_write_5m, cache_write_1h, cache_read FROM ai_price_current"
    ).fetchall()
    assert {Price(*r) for r in rows} == set(PRICES)
    limits = dict(db.execute("SELECT category, monthly_limit_microusd FROM ai_budget_current").fetchall())
    assert limits == {"learning": LEARNING.monthly_limit, "content": CONTENT.monthly_limit}
