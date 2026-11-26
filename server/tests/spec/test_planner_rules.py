"""Acceptance tests for the warm-up, daily-plan and mixed-run rules, and for the example pack files.
Run with:  python -m pytest spec/"""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from franca.study.planner_rules import (
    Card,
    build_today,
    check_lesson,
    game_items,
    games_for_level,
    goal_item_allowed,
    goal_items_today,
    library_label,
    mixed_run_candidates,
    mixed_run_updates_schedule,
    plan_today,
    release_held,
    select_warmup,
    text_coverage,
    word_is_known,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packs" / "fixture"
SCHEMAS = ROOT / "contracts" / "pack"
LESSON = yaml.safe_load((FIXTURE / "course" / "u05-l03.lesson.yaml").read_text())
CONFIG = yaml.safe_load((FIXTURE / "course-config.yaml").read_text())
WU, PLAN, MIX = CONFIG["warmup"], CONFIG["daily_plan"], CONFIG["mixed_run"]
GOALS, LIB = CONFIG["goals"], CONFIG["library"]
NOW = datetime(2026, 11, 11, 19, 30)
CORE = [e["item"] for e in LESSON["builds_on"] if e["weight"] == "core"]


def fresh(item, recall=0.97):
    return Card(item=item, recall=recall, due=NOW + timedelta(days=5), last_review=NOW - timedelta(days=2))


# --- the example files match their schemas
@pytest.mark.parametrize("schema,data", [("lesson.schema.json", LESSON), ("course-config.schema.json", CONFIG)])
def test_examples_are_valid(schema, data):
    validator = Draft202012Validator(json.loads((SCHEMAS / schema).read_text()))
    assert [e.message for e in validator.iter_errors(data)] == []


def test_schema_rejects_bad_item_id():
    bad = copy.deepcopy(LESSON)
    bad["teaches"] = ["Niet geen"]
    validator = Draft202012Validator(json.loads((SCHEMAS / "lesson.schema.json").read_text()))
    assert list(validator.iter_errors(bad))


# --- warm-up
def test_up_to_date_learner_gets_the_minimum_of_three():
    cards = {i: fresh(i) for i in CORE}
    cards["fx:lexeme:duur"] = fresh("fx:lexeme:duur", 0.91)
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert len(plan.recall_items) == 3 and not plan.reminder_items and not plan.offer_review_first
    assert plan.recall_items[0] == "fx:lexeme:duur"  # lowest recall first


def test_slipping_items_are_chosen_first_and_capped_at_six():
    cards = {i: fresh(i, 0.70 + n * 0.01) for n, i in enumerate(CORE)}
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert plan.offer_review_first is True  # 7 core items qualify, more than 6
    assert len(plan.recall_items) <= WU["bridge_max"] and plan.seconds <= WU["bridge_max_seconds"]
    assert plan.recall_items[0] == CORE[0]


def test_never_met_items_get_a_reminder_not_a_question():
    cards = {i: fresh(i) for i in CORE}
    del cards["fx:lexeme:duur"]  # lesson 2 skipped
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert plan.reminder_items == ["fx:lexeme:duur"]
    assert "fx:lexeme:duur" not in plan.recall_items


def test_items_reviewed_in_the_last_day_are_skipped():
    cards = {i: fresh(i, 0.60) for i in CORE}
    cards["fx:lexeme:kaas"].last_review = NOW - timedelta(hours=3)
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert "fx:lexeme:kaas" not in plan.recall_items


def test_lapses_qualify_an_item_with_high_recall():
    cards = {i: fresh(i) for i in CORE}
    cards["fx:grammar:word-order-v2"].lapses_30d = 2
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert plan.recall_items[0] == "fx:grammar:word-order-v2"


# --- daily plan brake
@pytest.mark.parametrize(
    "review,level,lesson,extra", [(5, "normal", True, True), (12, "reduced", True, False), (16, "review-only", False, False)]
)
def test_review_brake(review, level, lesson, extra):
    plan = plan_today(30, review, "fx:lesson:a1-u05-l03", PLAN)
    assert plan.level == level and (plan.lesson is not None) == lesson and plan.extra == extra


# --- mixed run
def test_mixed_run_draw_order_and_exclusions():
    cards = [
        Card("a", recall=0.70, due=NOW - timedelta(days=1)),
        Card("b", recall=0.85, due=NOW + timedelta(days=2)),
        Card("c", recall=0.97, due=NOW + timedelta(days=9)),
        Card("d", recall=0.88, last_review=NOW - timedelta(hours=2)),
        Card("e", recall=0.86, met=False),
        Card("f", recall=0.90, due=NOW + timedelta(days=3)),
    ]
    assert mixed_run_candidates(cards, {"a", "b", "c", "d", "f"}, NOW, MIX) == ["a", "b", "f"]


@pytest.mark.parametrize(
    "fmt,correct,done,expected",
    [("typed", True, 0, True), ("recognition", True, 0, False), ("recognition", False, 0, True), ("spoken", True, 1, False)],
)
def test_mixed_run_schedule_updates(fmt, correct, done, expected):
    assert mixed_run_updates_schedule(fmt, correct, done, MIX) is expected


# --- pack builder
ORDER = [
    "fx:lesson:a1-u05-l02",
    "fx:lesson:a1-u05-l03",
    "fx:lesson:a1-u05-l05",
    "fx:lesson:a1-u07-l01",
    "fx:lesson:a1-u07-l02",
    "fx:lesson:a2-u14-l02",
]
TAUGHT_BEFORE = set(CORE) | {"fx:grammar:possessive-determiners", "fx:chunk:mag-ik"}


def test_example_lesson_passes_the_builder():
    assert check_lesson(LESSON, TAUGHT_BEFORE, {}, ORDER, WU["preteach_max"]) == []


def test_builder_catches_deze_when_it_is_not_declared():
    bad = copy.deepcopy(LESSON)
    bad["exposure_only"] = [e for e in bad["exposure_only"] if e["item"] != "fx:grammar:demonstratives"]
    assert any("demonstratives" in p for p in check_lesson(bad, TAUGHT_BEFORE, {}, ORDER, WU["preteach_max"]))


def test_builder_refuses_exposure_items_as_production_targets():
    bad = copy.deepcopy(LESSON)
    bad["activities"][2]["production_targets"].append("fx:grammar:adjective-inflection")
    assert any("production target" in p for p in check_lesson(bad, TAUGHT_BEFORE, {}, ORDER, WU["preteach_max"]))


def test_builder_limits_preteaching_at_a1():
    bad = copy.deepcopy(LESSON)
    bad["preteach"].append("fx:lexeme:thee")
    assert any("preteach" in p for p in check_lesson(bad, TAUGHT_BEFORE, {}, ORDER, WU["preteach_max"]))


# --- reviewer's proposed extra cases
def met(item, recall=0.97, **kw):
    return Card(item=item, recall=recall, due=NOW + timedelta(days=5), last_review=NOW - timedelta(days=2), **kw)


def test_reminders_do_not_count_towards_the_minimum():
    cards = {i: met(i) for i in CORE}
    del cards["fx:lexeme:duur"]
    del cards["fx:lexeme:kaas"]
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert plan.reminder_items == ["fx:lexeme:duur", "fx:lexeme:kaas"] and len(plan.recall_items) == 3  # as WU0 row 3
    assert [k for k, _ in plan.order] == ["reminder", "reminder", "recall", "recall", "recall"]


def test_nothing_met_offers_the_earlier_lesson_not_review():
    plan = select_warmup(LESSON, {}, NOW, WU)
    assert plan.offer_earlier_lesson and not plan.offer_review_first and plan.recall_items == []
    assert len(plan.reminder_items) <= 2


def test_exactly_six_qualifying_does_not_offer_review_first():
    cards = {i: met(i, 0.6) for i in CORE[:6]} | {i: met(i) for i in CORE[6:]}
    assert select_warmup(LESSON, cards, NOW, WU).offer_review_first is False


def test_recall_threshold_is_strict():
    cards = {i: met(i) for i in CORE}
    cards["fx:lexeme:kaas"] = met("fx:lexeme:kaas", 0.90)
    cards["fx:lexeme:duur"] = met("fx:lexeme:duur", 0.899)
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert plan.recall_items[0] == "fx:lexeme:duur"  # qualifies; kaas at 0.90 is only a filler candidate


def test_one_lapse_does_not_qualify():
    cards = {i: met(i) for i in CORE}
    cards["fx:lexeme:kaas"].lapses_30d = 1
    cards["fx:lexeme:kaas"].recall = 0.99
    assert "fx:lexeme:kaas" not in select_warmup(LESSON, cards, NOW, WU).recall_items


def test_ties_keep_builds_on_order():
    cards = {i: met(i, 0.97) for i in CORE}
    assert select_warmup(LESSON, cards, NOW, WU).recall_items == CORE[:3]


def test_empty_builds_on_gives_no_bridge():
    lesson = copy.deepcopy(LESSON)
    lesson["builds_on"] = []
    plan = select_warmup(lesson, {}, NOW, WU)
    assert plan.order == [] and not plan.offer_review_first


def test_all_reviewed_today_gives_no_bridge():
    cards = {i: met(i) for i in CORE}
    for c in cards.values():
        c.last_review = NOW - timedelta(hours=1)
    assert select_warmup(LESSON, cards, NOW, WU).order == []


def test_minimum_wins_over_the_time_cap():
    cards = {i: met(i, seconds=40) for i in CORE}
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert len(plan.recall_items) == WU["bridge_min"]


def test_one_card_longer_than_the_cap_is_still_asked():
    cards = {i: met(i, 0.6, seconds=120) for i in CORE}
    assert len(select_warmup(LESSON, cards, NOW, WU).recall_items) == WU["bridge_min"]


def test_support_items_only_when_met_and_core_is_short():
    cards = {i: met(i) for i in CORE}
    cards["fx:grammar:possessive-determiners"] = met("fx:grammar:possessive-determiners", 0.5)
    plan = select_warmup(LESSON, cards, NOW, WU)
    assert plan.recall_items[0] == "fx:grammar:possessive-determiners"
    cards = {i: met(i, 0.6) for i in CORE}
    cards["fx:grammar:possessive-determiners"] = met("fx:grammar:possessive-determiners", 0.1)
    assert "fx:grammar:possessive-determiners" not in select_warmup(LESSON, cards, NOW, WU).recall_items
    cards = {i: met(i) for i in CORE}
    assert "fx:chunk:mag-ik" not in select_warmup(LESSON, cards, NOW, WU).reminder_items  # never met support: nothing


def test_duplicate_builds_on_entries_are_asked_once():
    lesson = copy.deepcopy(LESSON)
    lesson["builds_on"].append(dict(lesson["builds_on"][0]))
    cards = {i: met(i, 0.6) for i in CORE}
    items = select_warmup(lesson, cards, NOW, WU).recall_items
    assert len(items) == len(set(items))


@pytest.mark.parametrize("review,level", [(10, "normal"), (10.1, "reduced"), (15, "reduced"), (15.1, "review-only")])
def test_brake_boundaries(review, level):
    assert plan_today(30, review, "x", PLAN).level == level


def test_brake_needs_a_planned_time():
    with pytest.raises(ValueError):
        plan_today(0, 0, "x", PLAN)


def test_unknown_answer_format_is_refused():
    with pytest.raises(ValueError):
        mixed_run_updates_schedule("matching", True, 0, MIX)


@pytest.mark.parametrize("recall,expected", [(0.80, True), (0.92, True), (0.921, False), (0.799, False)])
def test_mixed_run_band_edges(recall, expected):
    cards = [Card("x", recall=recall, due=NOW + timedelta(days=3))]
    assert (mixed_run_candidates(cards, {"x"}, NOW, MIX) == ["x"]) is expected


# --- Vandaag keeps the lesson's due bridge items for the warm-up
def test_due_bridge_items_are_held_for_the_warm_up():
    cards = {i: met(i) for i in CORE}
    cards["fx:lexeme:duur"] = Card("fx:lexeme:duur", recall=0.82, due=NOW - timedelta(hours=5), last_review=NOW - timedelta(days=6))
    other = Card("fx:lexeme:fiets", recall=0.80, due=NOW - timedelta(hours=1), last_review=NOW - timedelta(days=9))
    today = build_today(30, [cards["fx:lexeme:duur"], other], LESSON, cards, NOW, WU, PLAN)
    assert today.held_for_warmup == ["fx:lexeme:duur"]
    assert today.review_items == ["fx:lexeme:fiets"]
    assert "fx:lexeme:duur" in today.warmup.recall_items


def test_held_items_return_when_the_lesson_is_not_started():
    cards = {i: met(i) for i in CORE}
    cards["fx:lexeme:duur"] = Card("fx:lexeme:duur", recall=0.82, due=NOW - timedelta(hours=5), last_review=NOW - timedelta(days=6))
    today = build_today(30, [cards["fx:lexeme:duur"]], LESSON, cards, NOW, WU, PLAN)
    assert release_held(today, lesson_started=False) == ["fx:lexeme:duur"]
    assert release_held(today, lesson_started=True) == []


def test_nothing_is_held_on_a_review_only_day():
    cards = {i: met(i) for i in CORE}
    cards["fx:lexeme:duur"] = Card(
        "fx:lexeme:duur", recall=0.82, due=NOW - timedelta(hours=5), last_review=NOW - timedelta(days=6), seconds=20
    )
    backlog = [Card(f"x{n}", recall=0.7, due=NOW - timedelta(days=1), seconds=20) for n in range(60)]
    today = build_today(30, backlog + [cards["fx:lexeme:duur"]], LESSON, cards, NOW, WU, PLAN)
    assert today.plan.level == "review-only" and today.held_for_warmup == [] and "fx:lexeme:duur" in today.review_items


def test_prediction_answers_point_at_options():
    p = LESSON["prediction"]
    assert all(0 <= a < len(p["options"]) for a in p["answers"])
    assert len(p.get("feedback", p["options"])) == len(p["options"])


# --- goal items (accepted 22 November 2026)
def test_goal_share_is_twenty_percent_after_the_brake():
    normal = plan_today(30, 5, "u05-l03", PLAN)
    reduced = plan_today(30, 12, "u05-l03", PLAN)
    review_only = plan_today(30, 20, None, PLAN)
    assert goal_items_today(12, normal, GOALS) == 2
    assert goal_items_today(12, reduced, GOALS) == 1  # halved with the new items
    assert goal_items_today(12, review_only, GOALS) == 0


def test_goal_cards_count_towards_the_review_limit():
    due = [Card(item="fx:lexeme:opgraving", due=NOW, seconds=60) for _ in range(12)]  # learned goal words, now due
    today = build_today(30, due, None, {}, NOW, WU, PLAN)
    assert today.plan.level == "reduced"  # 12 minutes of 30: the brake applies


def test_subject_terms_start_at_a2():
    assert not goal_item_allowed("subject_term", "a1", GOALS)
    assert goal_item_allowed("subject_term", "a2", GOALS)
    assert goal_item_allowed("goal_word", "pre-a1", GOALS)
    with pytest.raises(ValueError):
        goal_item_allowed("other", "a1", GOALS)


# --- library suggestions (accepted 22 November 2026)
def test_known_words_follow_lute_status_or_review():
    assert word_is_known(4, False) and word_is_known(99, False) and word_is_known(None, True)
    assert not word_is_known(3, False) and not word_is_known(None, False)


def test_names_and_numbers_are_left_out_of_coverage():
    toks = [{"lemma": w} for w in ["ik"] * 18 + ["opgraving", "scherf"]] + [
        {"lemma": "Gent", "is_name": True},
        {"lemma": "12", "is_number": True},
    ]
    assert text_coverage(toks, {"ik"}) == 0.9


@pytest.mark.parametrize(
    "coverage,medium,label",
    [
        (0.99, "text", "easy"),
        (0.98, "text", "easy"),
        (0.96, "text", "suggest"),
        (0.94, "text", None),
        (0.91, "audio", "suggest"),
        (0.91, "video", "suggest"),
        (0.89, "video", None),
    ],
)
def test_library_labels(coverage, medium, label):
    assert library_label(coverage, medium, LIB) == label


# --- games (course design section Games and puzzles, 22 November 2026)
def test_games_by_level():
    assert set(games_for_level("orientation", CONFIG)) == {"memory_game", "sound_game"}
    a1 = set(games_for_level("a1", CONFIG))
    assert "memory_game" not in a1 and {"crossword", "article_sort", "sound_game"} <= a1 and "story_game" not in a1
    assert {"collocation_match", "guess_the_word", "story_game"} <= set(games_for_level("b1", CONFIG))


def test_games_use_only_taught_items_due_first():
    cards = [
        Card(item="a", due=NOW - timedelta(days=1), recall=0.85, last_review=NOW - timedelta(days=3)),
        Card(item="b", due=NOW + timedelta(days=2), recall=0.88, last_review=NOW - timedelta(days=3)),
        Card(item="c", due=NOW - timedelta(days=1), recall=0.80, last_review=NOW - timedelta(days=3)),
    ]
    assert game_items(cards, {"a", "b"}, NOW, MIX, 10) == ["a", "b"]  # c is not taught
