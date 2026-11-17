"""False corrections are treated as seriously as missed ones."""
import re

import pytest

from glossary_data import demo
from stt.glossary import build
from stt.termfix import PREFIXES, correct_text

G = build(demo())
SINGLE_ALIASES = sorted(G.single)

# Ordinary Arabic words that begin with every supported prefix (and other common words).
ORDINARY = ["لكي", "للبرمجة", "للطلاب", "ولكن", "وبعدها", "وعندي", "والله", "والطلاب",
            "بالنهاية", "بالشكل", "بالبيت", "بدنا", "بيشتغل", "بعدما", "الامور", "الاخير",
            "التصميم", "لازم", "لتحويل", "لقراءة", "كلام", "كلها", "اي", "ان", "او", "انا",
            "تيم", "رانيا", "كاشف", "لوبي", "سبيسي", "ايش", "اعتمدنا", "المطلوب", "مكتبة"]


@pytest.mark.parametrize("word", ORDINARY)
def test_ordinary_arabic_words_are_never_changed(word):
    for slide in (None, ["run", "cache", "loop", "API", "AI", "SQL", "time", "space"]):
        raw = f"قال {word} اليوم"
        assert correct_text(raw, G, slide) == (raw, [])


WORD_ALIASES = [a for a in SINGLE_ALIASES
                if all(t.kind == "word" and not t.keep_arabic for t in G.single[a])]


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("alias", WORD_ALIASES)
def test_prefix_is_split_without_losing_characters(prefix, alias):
    raw = f"هون {prefix}{alias}، خلص"
    text, corr = correct_text(raw, G)
    c, = corr
    assert c["original"] == prefix + alias                      # exact raw span, nothing lost
    assert c["prefix"] == prefix
    assert raw[c["char_start"]:c["char_end"]] == prefix + alias
    assert text.startswith("هون ") and text.endswith("، خلص")


def test_alias_starting_like_a_prefix_is_matched_whole():
    # "الجوريثم" begins with "ال" but the whole word is the alias: no prefix is stripped
    _, (c,) = correct_text("الجوريثم", G)
    assert c["prefix"] == "" and c["original"] == "الجوريثم"


@pytest.mark.parametrize("raw,term", [
    ("رن التلفون وانا بالمحاضرة", "run"),      # "rang" (Jordanian) == approved alias of "run"
    ("دفعت كاش بالمقصف", "cache"),             # "cash" == approved alias of "cache"
    ("عملت لوب على الشارع", "loop"),
])
def test_exact_alias_collisions_stay_unchanged_without_full_evidence(raw, term):
    assert correct_text(raw, G)[1] == []
    assert correct_text(raw, G, [term])[1] == []                 # slide context alone is not enough


def test_exact_alias_collision_with_full_evidence_is_corrected_known_risk():
    """KNOWN, UNAVOIDABLE RISK: an ordinary Arabic word that exactly equals an approved alias
    is corrected when both evidence conditions hold. Documented in the README; reduce it by
    rejecting such aliases at instructor review (collision flag)."""
    text, corr = correct_text("الداتابيس دفعت كاش", G, ["cache"])
    assert [c["term"] for c in corr] == ["database", "cache"]
    assert text == "الـ database دفعت cache"


def test_hamza_spelling_of_acronym_is_not_matched():
    # multi-word aliases need exact keys; أ is not treated as ا
    assert all(c["term"] != "API" for c in correct_text("أي بي أي الداتابيس", G, ["API"])[1])


MIXED = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


@pytest.mark.parametrize("raw", [
    "سبيسی",          # Persian yeh (U+06CC) at the end                      (was -> "spaceی")
    "تايمک",          # Persian kaf (U+06A9) at the end                      (was -> "timeک")
    "ڤتايم",          # veh (U+06A4) at the start                            (was -> "ڤtime")
    "بايثونی.",       # Persian yeh before punctuation                        (was -> "Pythonی.")
    "پايثون",         # peh inside the word
    "گتايم",          # gaf at the start
    "تايمٓ",          # stray combining mark (U+0653) outside the core class
    "تايم‌",     # zero-width non-joiner (format character)
    "ﺗﺎﻳﻢ",           # Arabic presentation forms
])
def test_extended_arabic_letters_are_never_split_from_words(raw):
    """Regression (bug 1): non-basic letters were treated as punctuation and split off."""
    text, corr = correct_text(f"هون {raw} خلص", G, ["time", "space", "Python"])
    assert corr == [] and text == f"هون {raw} خلص"
    for word in text.split():
        assert not (MIXED.search(word) and re.search("[A-Za-z]", word)), word


@pytest.mark.parametrize("raw,expected", [
    ("«تايم»", "«time»"), ("(تايم)", "(time)"), ("تايم؟", "time؟"),
    ("تايم،", "time،"), ("تايم...", "time..."), ("\"تايم\"", "\"time\""),
])
def test_real_punctuation_is_still_separated(raw, expected):
    assert correct_text(raw, G)[0] == expected


def test_evidence_does_not_chain_through_dependent_corrections():
    """Regression (bug 2): 'ران' used the accepted acronym 'API' as its adjacent evidence."""
    raw = "الداتابيس واحد اثنين اي بي اي واحد اثنين ران"
    text, corr = correct_text(raw, G, ["API", "run"])
    terms = {c["term"]: c for c in corr}
    assert "run" not in terms                                   # only database is independent, 8 words away
    assert terms["API"]["evidence"] == ["slide_term", "adjacent_term:database"]
    assert text.endswith(" ران")
    # with an independent term within 3 words, the same short term is accepted
    _, corr = correct_text("اي بي اي واحد الداتابيس ران", G, ["API", "run"])
    assert [c["evidence"] for c in corr if c["term"] == "run"] == [["slide_term", "adjacent_term:database"]]


def test_latin_and_mixed_tokens_are_ignored():
    raw = "الـalgorithm Python3 API الجوريثمX"
    assert correct_text(raw, G, ["API"]) == (raw, [])
