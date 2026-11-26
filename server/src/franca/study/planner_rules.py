"""The warm-up, daily-plan and mixed-run rules agreed on 11 November 2026.

Stories C01-012, E06-007, E06-008, E15-022, and E06-010 for goals and the library. This module started as the
specification's reference version. The tests in tests/spec/test_planner_rules.py are its acceptance tests, and the
study engine is built on these functions. It uses the Python standard library only.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# Lessons and pack settings are YAML documents checked against the schemas in contracts/pack.
Lesson = dict[str, Any]
Config = dict[str, Any]


@dataclass
class Card:
    """What the scheduler knows about one item for one learner."""

    item: str
    met: bool = True  # False if the learner has never studied the item
    due: datetime | None = None
    recall: float = 1.0  # predicted recall now (FSRS retrievability), 0 to 1
    lapses_30d: int = 0  # times forgotten in the last 30 days
    last_review: datetime | None = None
    seconds: float = 15.0  # the learner's usual time for this card


@dataclass
class WarmupPlan:
    recall_items: list[str] = field(default_factory=list)  # asked as review questions
    reminder_items: list[str] = field(default_factory=list)  # never met: a reminder screen, no question
    offer_review_first: bool = False
    offer_earlier_lesson: bool = False
    seconds: float = 0.0
    order: list[tuple[str, str]] = field(default_factory=list)  # ('reminder'|'recall', item) in screen order


def _qualifies(card: Card, now: datetime, cfg: Config) -> bool:
    if not card.met:
        return True
    if card.due is not None and card.due <= now:
        return True
    return bool(card.recall < cfg["recall_below"] or card.lapses_30d >= cfg["lapses_in_30_days"])


def _recent(card: Card, now: datetime, hours: int) -> bool:
    return card.last_review is not None and now - card.last_review < timedelta(hours=hours)


def select_warmup(lesson: Lesson, cards: dict[str, Card], now: datetime, cfg: Config) -> WarmupPlan:
    """Choose the bridge items for a lesson's warm-up (reviewer's proposed version).

    Changes from the draft: reminders do not count towards bridge_min; review first is offered only for
    met items, and a never-met majority offers the earlier lesson; one ordered list keeps the screen order;
    bridge_min wins over bridge_max_seconds; duplicates in builds_on are ignored.
    """
    hours = cfg["skip_if_reviewed_within_hours"]
    reminder_s = cfg.get("reminder_seconds", 20)
    seen, entries = set(), []
    for e in lesson.get("builds_on", []):
        if e["item"] not in seen:
            seen.add(e["item"])
            entries.append(e)

    def pool(weight: str) -> Iterator[Card]:
        for e in entries:
            if e["weight"] == weight:
                card = cards.get(e["item"], Card(item=e["item"], met=False))
                if not (card.met and _recent(card, now, hours)):
                    yield card

    core = list(pool("core"))
    never = [c for c in core if not c.met]
    met_q = sorted((c for c in core if c.met and _qualifies(c, now, cfg)), key=lambda c: c.recall)
    plan = WarmupPlan(offer_review_first=len(met_q) > cfg["offer_review_first_above"])
    plan.offer_earlier_lesson = len(never) > len(core) / 2 if core else False
    recall = list(met_q)
    if len(recall) < cfg["bridge_min"]:
        recall += sorted((c for c in pool("support") if c.met and _qualifies(c, now, cfg)), key=lambda c: c.recall)
    if len(recall) < cfg["bridge_min"]:
        chosen = {c.item for c in recall}
        recall += sorted((c for c in core if c.met and c.item not in chosen), key=lambda c: c.recall)[: cfg["bridge_min"] - len(recall)]
    for c in never[: cfg.get("reminders_max", 2)]:
        plan.order.append(("reminder", c.item))
        plan.reminder_items.append(c.item)
        plan.seconds += reminder_s
    for c in recall:
        if len(plan.recall_items) >= cfg["bridge_max"]:
            break
        if len(plan.recall_items) >= cfg["bridge_min"] and plan.seconds + c.seconds > cfg["bridge_max_seconds"]:
            break
        plan.order.append(("recall", c.item))
        plan.recall_items.append(c.item)
        plan.seconds += c.seconds
    return plan


@dataclass
class DailyPlan:
    review_minutes: float
    lesson: str | None
    extra: bool
    new_items_factor: float
    level: str  # 'normal', 'reduced' or 'review-only'


def plan_today(planned_minutes: float, review_minutes: float, next_lesson: str | None, cfg: Config) -> DailyPlan:
    """The review brake. planned_minutes is the learner's daily time (T); review_minutes is due review (R)."""
    if planned_minutes <= 0:
        raise ValueError("planned_minutes must be above 0")
    share = round(review_minutes / planned_minutes, 3)  # 10 of 30 minutes is a third, not more
    if share > cfg["no_new_lesson_above"]:
        return DailyPlan(review_minutes, None, False, cfg["new_items_factor_when_reduced"], "review-only")
    if share > cfg["fewer_new_above"]:
        return DailyPlan(review_minutes, next_lesson, False, cfg["new_items_factor_when_reduced"], "reduced")
    return DailyPlan(review_minutes, next_lesson, True, 1.0, "normal")


@dataclass
class Today:
    plan: DailyPlan
    review_items: list[str]  # the review part of Vandaag
    held_for_warmup: list[str]  # due items kept back for the lesson's warm-up
    warmup: WarmupPlan | None


def build_today(
    planned_minutes: float,
    due: list[Card],
    lesson: Lesson | None,
    cards: dict[str, Card],
    now: datetime,
    warmup_cfg: Config,
    plan_cfg: Config,
) -> Today:
    """Build Vandaag. The warm-up of today's lesson is chosen first, so that due items the lesson builds on are
    kept out of the review part and asked in the warm-up, right before the new material."""
    warmup = select_warmup(lesson, cards, now, warmup_cfg) if lesson else None
    held = set(warmup.recall_items) if warmup else set()
    review = [c for c in due if c.item not in held]
    minutes = sum(c.seconds for c in review) / 60
    plan = plan_today(planned_minutes, minutes, lesson["id"] if lesson else None, plan_cfg)
    if plan.lesson is None:  # no lesson today: nothing is held back
        review, held = list(due), set()
        warmup = None
    held_list = [c.item for c in due if c.item in held]
    return Today(plan, [c.item for c in review], held_list, warmup)


def release_held(today: Today, lesson_started: bool) -> list[str]:
    """Items to put back in the review queue when the session ends. Held items return if the lesson was not started."""
    return [] if lesson_started else list(today.held_for_warmup)


def mixed_run_candidates(cards: list[Card], taught: set[str], now: datetime, cfg: Config) -> list[str]:
    """Items for a mixed run, in draw order: due items, then items in the recall band. Confusable pairs are
    added by the engine from the pack's confusable sets and are not covered here."""
    lo, hi = cfg["recall_band"]
    hours = cfg["skip_if_reviewed_within_hours"]
    pool = [c for c in cards if c.met and c.item in taught and not _recent(c, now, hours) and c.recall <= cfg["skip_above"]]
    due = sorted((c for c in pool if c.due is not None and c.due <= now), key=lambda c: c.recall)
    band = sorted((c for c in pool if c not in due and lo <= c.recall <= hi), key=lambda c: c.recall)
    return [c.item for c in due + band]


def mixed_run_updates_schedule(answer_format: str, correct: bool, updates_today: int, cfg: Config) -> bool:
    """Whether an answer in a mixed run changes the item's schedule.
    answer_format: 'typed', 'spoken', 'handwritten' (recall) or 'recognition'."""
    if answer_format not in ("typed", "spoken", "handwritten", "recognition"):
        raise ValueError(f"unknown answer format: {answer_format}")
    if updates_today >= cfg["updates_per_item_per_day"]:
        return False
    if answer_format == "recognition" and cfg["recognition_updates_only_on_failure"]:
        return not correct
    return True


def check_lesson(lesson: Lesson, taught_before: set[str], taught_in: dict[str, str], order: list[str], preteach_max: Config) -> list[str]:
    """Pack builder checks for one lesson. Returns a list of problems; empty means the lesson passes.

    taught_before: items taught in lessons earlier in course order; taught_in: item -> lesson that teaches it;
    order: lesson ids in course order.
    """
    problems = []
    own = set(lesson.get("teaches", [])) | set(lesson.get("preteach", []))
    builds = {e["item"] for e in lesson.get("builds_on", [])}
    exposure = {e["item"]: e["taught_in"] for e in lesson.get("exposure_only", [])}
    pos = {lid: i for i, lid in enumerate(order)}
    here = pos.get(lesson["id"])
    for act in lesson.get("activities", []):
        for item in act["items"]:
            if not (item in own or item in builds or item in exposure or item in taught_before):
                problems.append("{}: {} is used but not taught, listed or taught earlier".format(act["id"], item))
        for item in act.get("production_targets", []):
            if item in exposure:
                problems.append("{}: {} is exposure only and cannot be a production target".format(act["id"], item))
    for item in builds:
        if item not in taught_before:
            problems.append(f"builds_on: {item} is not taught earlier in the course")
    for item, lid in exposure.items():
        if here is not None and lid in pos and pos[lid] <= here:
            problems.append(f"exposure_only: {item} is taught in {lid}, which is not later")
    if here is None:
        problems.append("{} is not in the course order".format(lesson["id"]))
    for item, lid in exposure.items():
        if lid not in pos:
            problems.append(f"exposure_only: {item} names {lid}, which is not in the course order")
        elif item in taught_in and taught_in[item] != lid:
            problems.append(f"exposure_only: {item} is taught in {taught_in[item]}, not {lid}")
        if item in taught_before:
            problems.append(f"exposure_only: {item} is already taught earlier")
    listed = [e["item"] for e in lesson.get("builds_on", [])]
    for item in {i for i in listed if listed.count(i) > 1}:
        problems.append(f"builds_on: {item} is listed twice")
    for a, b in (("teaches", builds), ("preteach", builds), ("teaches", set(exposure)), ("preteach", set(exposure))):
        for item in set(lesson.get(a, [])) & b:
            problems.append(f"{a}: {item} is also in builds_on or exposure_only")
    heard = {i for act in lesson.get("activities", []) if act["step"] == "input" for i in act["items"]}
    for item in lesson.get("preteach", []):
        if item not in heard:
            problems.append(f"preteach: {item} is not used in the input")
        if item in taught_before:
            problems.append(f"preteach: {item} is taught earlier, so it is not new")
    core = sum(1 for e in lesson.get("builds_on", []) if e["weight"] == "core")
    if core > 8:
        problems.append(f"builds_on: {core} core items; more than 8 suggests the lesson depends on too much")
    limit = preteach_max.get(str(lesson.get("level", "")), 6)
    if len(lesson.get("preteach", [])) > limit:
        problems.append(f"preteach: {len(lesson['preteach'])} words, more than {limit} for this level")
    return problems


# --- Rules accepted on 22 November 2026 (goal items, library suggestions, games) -----------------------------

LEVELS = ["orientation", "pre-a1", "a1", "a2", "b1", "b2", "c1", "c2"]


def _at_least(level: str, minimum: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(minimum)


def goal_items_today(new_items: int, plan: DailyPlan, cfg: Config) -> int:
    """How many of today's new items may be goal words and subject terms (together, goal items).

    new_items is the number of new items the lesson would bring on a normal day. The share is applied after the
    review brake, so it is halved with the new items on a reduced day and is zero on a day with reviews only.
    Goal items that are already learned are ordinary cards: their reviews count towards the review limit
    through plan_today like any other due card."""
    if plan.level == "review-only" or new_items <= 0:
        return 0
    return int(new_items * plan.new_items_factor * cfg["goal_share_max"])


def goal_item_allowed(kind: str, learner_level: str, cfg: Config) -> bool:
    """Subject terms (kind 'subject_term') start at the level where the subject word lists begin.
    Goal words (kind 'goal_word') are allowed at every level."""
    if kind == "subject_term":
        return _at_least(learner_level, cfg["subject_terms_from"])
    if kind == "goal_word":
        return True
    raise ValueError(f"unknown goal item kind: {kind}")


def word_is_known(lute_status: int | None, pack_item_in_review: bool) -> bool:
    """A word counts as known when it is a library term at Lute status 4, 5 or 99, or a pack item in review."""
    return pack_item_in_review or lute_status in (4, 5, 99)


def text_coverage(tokens: list[dict[str, Any]], known: set[str]) -> float:
    """Share of running words the learner knows. tokens: dicts with 'lemma' and optional 'is_name' and
    'is_number'. Proper names and numbers are left out of the count."""
    counted = [t for t in tokens if not t.get("is_name") and not t.get("is_number")]
    if not counted:
        return 1.0
    return sum(1 for t in counted if t["lemma"] in known) / len(counted)


def library_label(coverage: float, medium: str, cfg: Config) -> str | None:
    """'easy' (texts at or above the easy-reading share), 'suggest', or None (not suggested; the learner can
    still open it and see its coverage). A learner's goals do not lower the thresholds."""
    if medium == "text":
        if coverage >= cfg["easy_reading_from"]:
            return "easy"
        return "suggest" if coverage >= cfg["suggest_text_from"] else None
    if medium in ("audio", "video"):
        return "suggest" if coverage >= cfg["suggest_audio_video_from"] else None
    raise ValueError(f"unknown medium: {medium}")


def games_for_level(level: str, cfg: Config) -> list[str]:
    """Games offered at a learner's level: from each game's first level, and Memory only up to its last level."""
    out = []
    for game, rule in cfg["games"].items():
        if not _at_least(level, rule["from"]):
            continue
        if "until" in rule and LEVELS.index(level) > LEVELS.index(rule["until"]):
            continue
        out.append(game)
    return out


def game_items(cards: list[Card], taught: set[str], now: datetime, mix_cfg: Config, size: int) -> list[str]:
    """Items for a game: only taught items, due ones first and then nearly due ones (the mixed-run recall band).
    Answers are scheduled with mixed_run_updates_schedule."""
    return mixed_run_candidates(cards, taught, now, mix_cfg)[:size]
