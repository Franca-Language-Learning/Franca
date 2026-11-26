"""Tests for lemma keys (spec/item_keys.py). The pack builder has to pass the same cases."""

import unicodedata

import pytest

from franca.catalogue.item_keys import ITEM_KEY, KeyError_, Lexeme, assign_keys, base_key, slug


@pytest.mark.parametrize(
    "lemma, key",
    [
        ("café", "nl:lexeme:cafe"),
        ("'s avonds", "nl:lexeme:s-avonds"),
        ("Brussel", "nl:lexeme:brussel"),
        ("zo'n", "nl:lexeme:zo-n"),
        ("ruïne", "nl:lexeme:ruine"),
        ("ĳs", "nl:lexeme:ijs"),  # the ij ligature becomes two letters
        ("e-mail", "nl:lexeme:e-mail"),
        ("tot  en met", "nl:lexeme:tot-en-met"),
        ("cœur", "nl:lexeme:coeur"),  # œ has no accent to remove
        ("Straße", "nl:lexeme:strasse"),
        ("København", "nl:lexeme:kobenhavn"),
        ("Łódź", "nl:lexeme:lodz"),
        ("e\u2011mail", "nl:lexeme:e-mail"),  # non-breaking hyphen
        ("chauf\u00adfeur", "nl:lexeme:chauffeur"),  # soft hyphen
    ],
)
def test_four_steps(lemma, key):
    assert base_key("nl", Lexeme(lemma, "X")) == key


def test_numbering_follows_input_order():
    keys = assign_keys("nl", [Lexeme("een", "DET"), Lexeme("één", "NUM"), Lexeme("zijn", "AUX"), Lexeme("zijn", "PRON")])
    assert keys == {
        ("een", "DET"): "nl:lexeme:een",
        ("één", "NUM"): "nl:lexeme:een-2",
        ("zijn", "AUX"): "nl:lexeme:zijn",
        ("zijn", "PRON"): "nl:lexeme:zijn-2",
    }


def test_existing_keys_are_kept_and_numbers_are_not_reused():
    earlier = {("één", "NUM"): "nl:lexeme:een", ("een", "DET"): "nl:lexeme:een-2"}
    # één has been removed from the new version; its key stays reserved
    keys = assign_keys("nl", [Lexeme("een", "DET"), Lexeme("Een", "PROPN")], existing=earlier)
    assert keys[("een", "DET")] == "nl:lexeme:een-2"
    assert keys[("Een", "PROPN")] == "nl:lexeme:een-3"


def test_other_scripts_need_a_romanised_key():
    with pytest.raises(KeyError_, match="romanised"):
        base_key("zh", Lexeme("你好", "INTJ"))
    assert base_key("zh", Lexeme("你好", "INTJ", romanised="nǐ hǎo")) == "zh:lexeme:ni-hao"
    assert base_key("fa", Lexeme("سلام", "INTJ", romanised="salâm")) == "fa:lexeme:salam"


def test_left_over_characters_stop_the_build():
    with pytest.raises(KeyError_, match="d.w.z."):
        slug("d.w.z.")


def test_keys_fit_the_database_rule():
    keys = assign_keys("nl", [Lexeme("a", "NOUN"), Lexeme("x" * 190, "NOUN")])
    assert all(ITEM_KEY.fullmatch(k) for k in keys.values())
    with pytest.raises(KeyError_, match="format"):
        assign_keys("nl", [Lexeme("x" * 191, "NOUN")])


def test_database_accepts_the_keys():
    import sqlite3
    from pathlib import Path

    db = sqlite3.connect(":memory:")
    db.executescript((Path(__file__).resolve().parents[3] / "contracts" / "db" / "schema.sql").read_text())
    db.execute(
        "INSERT INTO catalogue_pack (language, name_en, script, direction, created_at) "
        "VALUES ('nl', 'Dutch', 'Latn', 'ltr', '2026-11-21T00:00:00.000Z')"
    )
    keys = assign_keys("nl", [Lexeme("'s avonds", "ADV"), Lexeme("één", "NUM"), Lexeme("een", "DET")])
    for k in keys.values():
        db.execute("INSERT INTO catalogue_item (pack_id, item_key, kind) VALUES (1, ?, 'lexeme')", (k,))


def test_the_same_word_in_another_unicode_form_keeps_its_key():
    earlier = {(unicodedata.normalize("NFC", "één"), "NUM"): "nl:lexeme:een"}
    keys = assign_keys("nl", [Lexeme(unicodedata.normalize("NFD", "één"), "NUM")], existing=earlier)
    assert list(keys.values()) == ["nl:lexeme:een"]


def test_keys_of_removed_words_are_not_given_out_again():
    keys = assign_keys("nl", [Lexeme("een", "DET")], existing={}, reserved={"nl:lexeme:een"})
    assert keys[("een", "DET")] == "nl:lexeme:een-2"


def test_language_code_is_checked():
    with pytest.raises(KeyError_, match="ISO 639"):
        base_key("nl-BE", Lexeme("huis", "NOUN"))
