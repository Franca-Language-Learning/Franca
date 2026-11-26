"""Spending limits for hosted AI calls, applied by Franca before each call.

Decision of 21 November 2026: the limit is enforced on Franca's side, not in the
provider's console, and usage is recorded for every call (table ai_request).

How it works
------------
1. Before a call, the model adapter estimates its highest possible cost. Each prompt
   token is priced at the highest prompt rate of the model (a cache write costs more
   than plain input), and the output allowance (max_tokens) is added.
2. The call is refused when that estimate, added to what has been spent this month,
   including calls still running, would go over the monthly limit for its category.
   It is also refused when the learner's spending today, including their calls still
   running, would go over the daily limit per learner. "Today" is the learner's own
   day, which starts at day_starts_hour in their time zone (identity_learner), as for
   the rest of the app. The month is the calendar month in UTC.
3. When the call is allowed, a pending row with the estimate is written to ai_request
   in the same transaction (BEGIN IMMEDIATE), so every worker process sees it. After
   the call, the row is updated with the token counts the provider returns and the
   price in force (view ai_price_current).
4. The owner gets a message when spending passes 50% and 80% of the limit, and when
   the limit is reached or the first call of the month is refused for it. Each
   message is sent no more than one time a month (table ai_budget_alert).

When a call is refused, the app goes on without it (FALLBACK below). Lessons and
review keep working, because answers are checked by the pack's rules, the accepted
answers and LanguageTool before any AI model is used.

First limits (chosen on 21 November 2026)
-----------------------------------------
learning: 40 dollars a month, and 3 dollars per learner per day.
content: 60 dollars a month for pack-building jobs (translations, subtitles).

The learning limit is about twice the estimate in FIRST_ESTIMATE for two learners
(18.71 dollars a month). The daily limit is about ten times the estimate for one
day. A long study day stays under it, and a fault that keeps repeating calls is
stopped. Both are starting values. The usage report after two weeks of real use
is the basis for the next values. Prices are in US dollars because the provider
bills in dollars.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MICRO = 1_000_000  # micro-dollars per dollar


@dataclass(frozen=True)
class Price:
    """Price of one model tier, in micro-dollars per million tokens."""

    model: str
    min_prompt_tokens: int
    input: int
    output: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read: int


@dataclass(frozen=True)
class Usage:
    """Token counts for one call, as the provider returns them."""

    input: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output: int = 0

    @property
    def prompt(self) -> int:
        return self.input + self.cache_write_5m + self.cache_write_1h + self.cache_read


@dataclass(frozen=True)
class Budget:
    monthly_limit: int  # micro-dollars
    learner_daily_limit: int | None  # micro-dollars; None for content jobs
    warn_first: float = 0.5
    warn_second: float = 0.8


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None  # 'no_price', 'monthly_limit' or 'learner_daily_limit'


def tier_for(prices: list[Price], model: str, prompt_tokens: int) -> Price | None:
    """The price tier for a prompt of this size: the tier with the highest start at or below it."""
    tiers = [p for p in prices if p.model == model and p.min_prompt_tokens <= prompt_tokens]
    return max(tiers, key=lambda p: p.min_prompt_tokens) if tiers else None


def cost(usage: Usage, price: Price) -> int:
    """Cost in micro-dollars, rounded down, as in the view ai_request_cost."""
    return (
        usage.input * price.input
        + usage.cache_write_5m * price.cache_write_5m
        + usage.cache_write_1h * price.cache_write_1h
        + usage.cache_read * price.cache_read
        + usage.output * price.output
    ) // MICRO


def estimate(prices: list[Price], model: str, prompt_tokens: int, max_output_tokens: int) -> int | None:
    """Highest possible cost of a call. Each prompt token is priced at the highest prompt rate of
    the tier, and the output allowance is added. ``prices`` are the prices in force."""
    price = tier_for(prices, model, prompt_tokens)
    if price is None:
        return None
    top_rate = max(price.input, price.cache_write_5m, price.cache_write_1h, price.cache_read)
    return (prompt_tokens * top_rate + max_output_tokens * price.output) // MICRO


def decide(estimated: int | None, month_spent: int, budget: Budget, learner_day_spent: int = 0) -> Decision:
    """Whether a call may be sent. Every figure is in micro-dollars.

    ``month_spent`` and ``learner_day_spent`` come from the view ai_request_cost, in which pending
    calls count at their estimate, so calls still running are included.
    """
    if estimated is None:
        return Decision(False, "no_price")
    if month_spent + estimated > budget.monthly_limit:
        return Decision(False, "monthly_limit")
    if budget.learner_daily_limit is not None and learner_day_spent + estimated > budget.learner_daily_limit:
        return Decision(False, "learner_daily_limit")
    return Decision(True)


def new_alerts(spent: int, budget: Budget, already_sent: set[str], refused: bool = False) -> list[str]:
    """Warning levels reached this month that have not been sent yet.

    Calls that would pass the limit are refused, so spending seldom reaches it exactly. The
    limit_reached message is therefore also sent at the first refusal for the monthly limit
    (``refused``). A level that was passed earlier but not sent, for example after a restart,
    is sent now.
    """
    levels = [
        ("first_warning", spent >= budget.warn_first * budget.monthly_limit),
        ("second_warning", spent >= budget.warn_second * budget.monthly_limit),
        ("limit_reached", refused or spent >= budget.monthly_limit),
    ]
    return [name for name, reached in levels if reached and name not in already_sent]


# What the app does when a call is refused.
FALLBACK = {
    "feedback": "Feedback from the pack's rules, the accepted answers and LanguageTool only, with a note that AI feedback is paused.",
    "conversation": "The conversation screen says that AI conversation is paused until the limit is raised or the month ends.",
    "handwriting": "The learner is asked to type the answer, or to rate a handwritten answer themselves.",
    "speech_recognition": "The local recogniser in the speech container is used, which needs no hosted model.",
    "explanation": "The written explanation from the pack is shown.",
    "classification": "The answer is marked for the owner's review queue and is not classified.",
    "translation": "The job stops and waits for the next month or a higher limit.",
    "content_generation": "The job stops and waits for the next month or a higher limit.",
}


@dataclass(frozen=True)
class Activity:
    """Expected use per learner per day, for the first estimate."""

    purpose: str
    model: str
    calls_per_day: int
    usage: Usage = field(default_factory=Usage)


# Assumptions behind the first learning limit (per learner per day). Cache reads are the
# parts of the prompt that repeat between calls (instructions, conversation so far).
FIRST_ESTIMATE = [
    Activity("conversation", "claude-sonnet-5-5", 30, Usage(input=1000, cache_read=3000, output=150)),
    Activity("feedback", "claude-sonnet-5-5", 20, Usage(input=500, cache_read=1500, output=300)),
    Activity("handwriting", "claude-sonnet-5-5", 40, Usage(input=1100, cache_read=400, output=50)),
    Activity("classification", "claude-haiku-5-5", 100, Usage(input=200, cache_read=800, output=50)),
]


def month_estimate(prices: list[Price], activities: list[Activity], learners: int, days: int = 30) -> int:
    """Estimated spending in a month, in micro-dollars."""
    per_day = 0
    for a in activities:
        price = tier_for(prices, a.model, a.usage.prompt)
        if price is None:
            raise ValueError(f"no price for {a.model} at {a.usage.prompt} prompt tokens")
        per_day += a.calls_per_day * cost(a.usage, price)
    return per_day * learners * days
