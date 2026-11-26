"""Item keys for words (lexemes) in a language pack.

Decision of 21 November 2026: the lemma key rule from design/content-base.md is part of
the pack format.

A lemma key is made from the lemma in four steps:

1. Remove the accents (café becomes cafe, één becomes een). Latin letters that have no accent
   to remove are written as plain letters: œ as oe, æ as ae, ß as ss, ø as o, ł as l.
2. Put the word in lower case.
3. Replace spaces, apostrophes and dashes with hyphens ('s avonds becomes -s-avonds). Hyphens
   at the start or end are dropped and a run of hyphens becomes one, so the result is s-avonds.
   Invisible formatting characters, such as a soft hyphen, are removed.
4. Put the language code and ``:lexeme:`` in front (nl:lexeme:s-avonds).

Two lexemes can end up with the same key: een and één, or zijn the verb and zijn the
pronoun. A lexeme is identified by its lemma (in Unicode form NFC) and its part of speech. The first lexeme
gets the plain key and the next ones get -2, -3 and so on (nl:lexeme:een-2). The first is
the one that comes first in the input, which is in frequency order in the lexicon build.

Keys stay the same from one pack version to the next. Learner history refers to items by
key, so a lexeme that already has a key keeps it. A number that has been used is not
given to another lexeme, even after the first one is removed from the pack: the builder
passes every item key the pack has ever had (catalogue_item keeps them all) as ``reserved``.
If the tagger gives a word a new part of speech between builds, the word gets a new key,
so the builder lists such changes for review.

A lemma with characters that are left over after the four steps (a full stop in d.w.z.,
or any script other than Latin, such as Mandarin or Persian) has no automatic key. The
person building the pack gives it a romanised key by hand (``romanised``), which goes through the same
steps. Without one, the build stops with an error that names the lemma.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Same rule as the CHECK on catalogue_item.item_key in db/tables.sql.
ITEM_KEY = re.compile(r"[a-z0-9:#_-]{5,200}")
LANGUAGE = re.compile(r"[a-z]{2,3}")  # ISO 639 code, as catalogue_pack.language
_SLUG_ALLOWED = re.compile(r"[a-z0-9-]+")
# Latin letters that Unicode does not split into a base letter and an accent.
_PLAIN = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "ß": "ss",
        "ẞ": "SS",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "TH",
        "đ": "d",
        "Đ": "D",
        "ħ": "h",
        "Ħ": "H",
        "ı": "i",
    }
)
_SEPARATORS = re.compile(r"[\s'\u2019\u2010-\u2015\u2212]+")  # spaces, apostrophes, dashes


class KeyError_(ValueError):
    """A lemma that cannot be turned into a key without a romanised form."""


@dataclass(frozen=True)
class Lexeme:
    lemma: str
    upos: str  # part of speech (Universal Dependencies tag)
    romanised: str | None = None  # given by hand when the lemma is not in Latin script


def slug(text: str) -> str:
    """Steps 1 to 3. Raises KeyError_ when characters are left that a key cannot hold."""
    visible = "".join(c for c in text if unicodedata.category(c) != "Cf")
    no_accents = "".join(c for c in unicodedata.normalize("NFKD", visible.translate(_PLAIN)) if not unicodedata.combining(c))
    lower = no_accents.lower()
    hyphened = _SEPARATORS.sub("-", lower)
    result = re.sub(r"-{2,}", "-", hyphened).strip("-")
    if not result or not _SLUG_ALLOWED.fullmatch(result):
        raise KeyError_(f"no automatic key for {text!r}: give a romanised key")
    return result


def base_key(language: str, lexeme: Lexeme) -> str:
    """The key before numbering (all four steps)."""
    if not LANGUAGE.fullmatch(language):
        raise KeyError_(f"language code {language!r} is not a lower-case ISO 639 code")
    return f"{language}:lexeme:{slug(lexeme.romanised or lexeme.lemma)}"


def identity(lexeme: Lexeme) -> tuple[str, str]:
    """What identifies a lexeme from one build to the next."""
    return unicodedata.normalize("NFC", lexeme.lemma), lexeme.upos


def assign_keys(
    language: str, lexemes: list[Lexeme], existing: dict[tuple[str, str], str] | None = None, reserved: set[str] | None = None
) -> dict[tuple[str, str], str]:
    """Keys for every lexeme, keyed by its identity (lemma in NFC, part of speech).

    ``existing`` has the keys of lexemes from earlier pack versions, which are kept.
    ``reserved`` has every item key the pack has had, including those of removed lexemes;
    none of them is given out again. New lexemes get the plain key if it is free, otherwise
    the lowest free number from 2 up.
    """
    keys = {(unicodedata.normalize("NFC", lemma), upos): key for (lemma, upos), key in (existing or {}).items()}
    used = set(keys.values()) | set(reserved or ())
    for lx in lexemes:
        ident = identity(lx)
        if ident in keys:
            continue
        base = base_key(language, lx)
        key, n = base, 2
        while key in used:
            key, n = f"{base}-{n}", n + 1
        if not ITEM_KEY.fullmatch(key):
            raise KeyError_(f"key {key!r} for {lx.lemma!r} does not fit the item key format")
        keys[ident] = key
        used.add(key)
    return keys
