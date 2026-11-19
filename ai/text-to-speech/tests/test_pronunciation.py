"""Pronunciation dictionary: applied to the spoken text only, before any engine."""
import json
from pathlib import Path

import pytest

from conftest import FakeEngine
from tts import PhraseError, Pronunciations, Synthesizer, TTSConfig
from tts.pronunciation import strip_diacritics

DEFAULT = Path(__file__).resolve().parents[1] / "pronunciation.json"
REQUIRED = ["الرصيفة", "الحسا", "الشيدية", "صويلح", "ناعور", "الأزرق", "الريشة", "وادي عربة", "ضانا",
            "المغنيسيوم", "البوتاسيوم", "المنغنيز", "اليورانيوم"]


def test_default_dictionary_has_the_words_and_no_typos():
    book = Pronunciations(DEFAULT)
    assert set(REQUIRED) <= set(book.entries)
    assert book.check() == []                  # every spoken form is the same word with diacritics
    assert {"places_jordan", "science"} <= set(book.groups)


def test_words_are_replaced_with_prefixes_and_whole_words_only():
    book = Pronunciations(DEFAULT)
    text = ("اكتشف في منطقة الرصيفة والحسا وبالرصيفة وللرصيفة، وفي وادي عربة، وصويلح. "
            "كلوريد البوتاسيوم والمغنيسيوم. الرصيفات و الأزرقان لا تتغير، والرُّصَيْفَة المشكولة كذلك.")
    assert book.apply(text) == (
        "اكتشف في منطقة الرُّصَيْفَة والحَسَا وبالرُّصَيْفَة وللرُّصَيْفَة، وفي وَادِي عَرَبَة، وصُوَيْلِح. "
        "كلوريد البُوتَاسِيُوم والمَغْنِيسِيُوم. الرصيفات و الأزرقان لا تتغير، والرُّصَيْفَة المشكولة كذلك.")
    assert book.apply("وادي  عربة") == "وَادِي عَرَبَة"            # spaces between the words do not matter
    assert Pronunciations(DEFAULT, enabled=False).apply("الرصيفة") == "الرصيفة"


def test_applied_before_the_engine_and_the_shown_text_is_unchanged(tmp_path):
    cfg = TTSConfig(cache=False, cache_dir=str(tmp_path / "cache"), pronunciation_file=str(DEFAULT))
    for raw in (False, True):                                  # Piper/Edge-style and Gemini-style engines
        engine = FakeEngine(raw_text=raw, name="gemini" if raw else "piper")
        tts = Synthesizer(cfg, engine=engine)
        text = "يوجد اليورانيوم في الرصيفة."
        tts.synthesize(text, tmp_path / f"out{raw}")
        assert text == "يوجد اليورانيوم في الرصيفة."             # the caller's text is not touched
        spoken = " ".join(t for t, _, _ in engine.calls)
        assert "اليُورَانِيُوم" in spoken and "الرُّصَيْفَة" in spoken


def test_adding_a_word_is_saved_and_used(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"_about": "test", "places": {"الحسا": "الحَسَا"}}, ensure_ascii=False),
                    encoding="utf-8")
    book = Pronunciations(path)
    book.add("الشيدية", "الشِّيدِيَّة")
    book.add("الحسا", "الحِسَا", group="places")              # replaces the old entry
    assert Pronunciations(path).entries == {"الحسا": "الحِسَا", "الشيدية": "الشِّيدِيَّة"}
    assert json.loads(path.read_text(encoding="utf-8"))["custom"] == {"الشيدية": "الشِّيدِيَّة"}
    assert book.apply("في الشيدية") == "في الشِّيدِيَّة"
    with pytest.raises(PhraseError, match="same word"):
        book.add("الريشة", "الرِّيشَات")
    assert book.remove("الشيدية") and book.apply("الشيدية") == "الشيدية"
    assert strip_diacritics("الرُّصَيْفَة") == "الرصيفة"
