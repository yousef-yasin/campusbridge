import copy
import json

import pytest

from glossary_data import demo
from stt import GlossaryError
from stt.glossary import build, comparison_key, compute_sha256, load_glossary, seal


def _write(tmp_path, data, name="g.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def test_load_valid_glossary(tmp_path):
    g = load_glossary(_write(tmp_path, demo()))
    assert g.info == {"course": "DEMO101", "version": 1, "sha256": demo()["sha256"]}
    assert [t.term for t in g.single["الجوريثم"]] == ["algorithm"]
    assert ("ران", "اكسبريمنت") in g.multi and ("اي", "بي", "اي") in g.multi
    assert g.max_phrase_words == 3


def test_only_approved_aliases_are_loaded():
    g = build(demo())
    assert "الجورزم" not in g.single                 # proposed
    assert ("اي", "اي") not in g.multi                # proposed acronym pronunciation
    data = demo()
    data["terms"][0]["aliases"][0]["status"] = "rejected"
    g = build(seal(data))
    assert "الجوريثم" not in g.single


def test_fuzzy_index_only_long_word_aliases():
    g = build(demo())
    keys = {k for k, _ in g.fuzzy}
    assert "ابليمنتيشن" in keys and "الجوريثم" in keys
    assert "تايم" not in keys and "ران" not in keys and "سيكول" not in keys


def test_hash_mismatch_rejected(tmp_path):
    data = demo()
    data["terms"][4]["aliases"][0]["ar"] = "تايمز"       # edited after publishing
    with pytest.raises(GlossaryError, match="integrity"):
        load_glossary(_write(tmp_path, data))


def test_hash_independent_of_formatting_and_key_order(tmp_path):
    data = demo()
    reordered = dict(reversed(list(data.items())))
    p = tmp_path / "compact.json"
    p.write_text(json.dumps(reordered, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    assert load_glossary(p).sha256 == data["sha256"]
    assert compute_sha256(data) == data["sha256"]


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.update(schema=2), "schema"),
    (lambda d: d.update(version=0), "version"),
    (lambda d: d.update(version="1"), "version"),
    (lambda d: d.pop("course"), "course"),
    (lambda d: d["terms"][0].update(kind="noun"), "kind"),
    (lambda d: d["terms"][0].update(term="خوارزمية"), "Latin"),
    (lambda d: d["terms"][0]["aliases"][0].update(ar="algoريثم"), "Arabic words"),
    (lambda d: d["terms"][0]["aliases"][0].update(ar="الجوريثم  "), "outer spaces"),
    (lambda d: d["terms"][0]["aliases"][0].update(status="ok"), "status"),
    (lambda d: d["terms"][7]["aliases"][0].update(ar="رانات"), "more than 3"),        # short too long
    (lambda d: d["terms"][4]["aliases"][0].update(ar="تيم"), "use kind 'short'"),    # word too short
    (lambda d: d["terms"][10]["aliases"][0].update(ar="ابي"), "at least 2 words"),   # acronym_letters
    (lambda d: d["terms"][12]["aliases"][0].update(ar="سي كول"), "single word"),     # acronym_word
    (lambda d: d["terms"][6].update(term="experiment"), "at least 2 words"),         # phrase term
    (lambda d: d["terms"][5]["aliases"][0].update(ar="تايم"), "approved for both"),  # duplicate alias
    (lambda d: d.update(never_correct="بدنا"), "never_correct"),
])
def test_invalid_glossaries_rejected(mutate, msg):
    data = copy.deepcopy(demo())
    mutate(data)
    with pytest.raises(GlossaryError, match=msg):
        build(seal(data))


@pytest.mark.parametrize("name", [" time", "time ", "run  experiment", "run\texperiment",
                                  "run experiment", "time\n"])
def test_term_names_with_bad_whitespace_rejected(name):
    """Regression (bug 3): ' time  ' was accepted and inserted extra spaces into text."""
    data = demo()
    data["terms"][4]["term"] = name
    with pytest.raises(GlossaryError, match="whitespace"):
        build(seal(data))


def test_non_nfc_entries_rejected_not_rewritten():
    decomposed = "café"                                  # NFD "café"
    data = demo()
    data["terms"][4]["term"] = decomposed
    with pytest.raises(GlossaryError, match="NFC"):
        build(seal(data))
    data = demo()
    data["never_correct"] = ["أن"]           # alef + combining hamza (NFC: أن)
    with pytest.raises(GlossaryError, match="NFC"):
        build(seal(data))
    data = demo()
    data["terms"][4]["aliases"][0]["ar"] = "أيم"
    with pytest.raises(GlossaryError):                         # rejected; never silently normalized
        build(seal(data))
    composed = demo()
    composed["terms"][4]["term"] = "café"
    assert any(t.term == "café" for t in build(seal(composed)).terms)


def test_bad_sha256_format_and_missing_file(tmp_path):
    with pytest.raises(GlossaryError, match="sha256"):
        build({**demo(), "sha256": "XYZ"})
    with pytest.raises(GlossaryError, match="not found"):
        load_glossary(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(GlossaryError, match="cannot read"):
        load_glossary(bad)


def test_comparison_key_is_conservative():
    assert comparison_key("الـجُوريثم") == "الجوريثم"            # tatweel + diacritics removed
    for a, b in [("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")]:
        assert comparison_key(a) != comparison_key(b)            # no letter is mapped to another
    assert comparison_key("مكتبة") == "مكتبة"


def test_never_correct_keys():
    assert build(demo()).never_correct == {"بدنا", "بعدما"}
