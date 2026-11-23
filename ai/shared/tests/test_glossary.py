"""The shared glossary: format compatible with speech-to-text, integrity, prompt rules, meaning check."""
import json
import sys
import types
from pathlib import Path

import pytest

from cb_shared import GlossaryError, load_glossary
from cb_shared.glossary import DEFAULT_PATH, Glossary, canonical_sha256

STT_SRC = Path(__file__).resolve().parents[2] / "speech-to-text" / "src"


def test_default_glossary_loads_with_the_required_terms():
    g = load_glossary()
    assert (g.course, g.version) == ("CB-GENERAL", 2)               # 2: health terms of the Cancer file
    assert g.entries["sampling distribution"].meaning == "توزيع المعاينة"
    assert g.entries["central limit theorem"].meaning == "نظرية النهاية المركزية"
    domains = {e.domain for e in g.entries.values()}
    assert {"statistics", "information security", "machine learning", "health"} <= domains
    assert g.entries["biopsy"].meaning == "الخزعة"


def test_integrity_check_refuses_an_edited_file(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["terms"][0]["meaning_ar"] = "معنى آخر"
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(GlossaryError, match="integrity"):
        load_glossary(path)
    data["version"] = 3
    data["sha256"] = canonical_sha256(data)                       # a new, sealed version is fine
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_glossary(path).version == 3


@pytest.mark.skipif(not (STT_SRC / "stt" / "glossary.py").is_file(), reason="speech-to-text module not present")
def test_speech_to_text_loader_accepts_the_same_file():
    """Its glossary.py (unchanged) loads our file: same schema and the same sha256 rule."""
    package = types.ModuleType("stt")
    package.__path__ = [str(STT_SRC / "stt")]
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "stt" or k.startswith("stt.")}
    sys.modules["stt"] = package
    try:
        from stt.glossary import compute_sha256, load_glossary as stt_load
        g = stt_load(DEFAULT_PATH)
        data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        assert (g.course, g.version, g.sha256) == ("CB-GENERAL", 2, compute_sha256(data))
        assert len(g.terms) == len(load_glossary().entries)
    finally:
        for k in [k for k in sys.modules if k == "stt" or k.startswith("stt.")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_find_and_prompt_rules():
    g = load_glossary()
    text = "The Sampling Distribution of the Mean and the standard deviation. A sample."
    assert [e.term for e in g.find(text)] == ["sampling distribution of the mean", "standard deviation", "sample"]
    rules = g.prompt_rules(text, "mixed")
    assert "- sampling distribution of the mean = توزيع المعاينة للمتوسط" in rules
    assert "- standard deviation = الانحراف المعياري" in rules
    assert g.prompt_rules(text, "ar") == rules and g.prompt_rules(text, "en") == ""
    assert g.prompt_rules("no terms here", "mixed") == ""


def test_wrong_meanings():
    g = load_glossary()
    # Real case: CLT slide 7, an answer translated sampling distribution wrongly.
    bad = "تعتمد على فكرة sampling distribution (التوزيع العشوائي لعينة ما)."
    assert g.wrong_meanings([bad]) == [
        "'sampling distribution' explained as «التوزيع العشوائي لعينة ما», glossary: «توزيع المعاينة»"]
    good = ["تعتمد على Sampling Distribution (توزيع المعاينة).",
            "يوضح Central Limit Theorem (نظرية الحد المركزي)",            # an accepted wording
            "ويقترب من التَّوْزِيع الطَّبِيعِيّ (normal distribution).",     # «meaning (term)», with diacritics
            "Integrity (النزاهة) و Availability (الإتاحة)",
            "يُحسب z-score بالمعادلة.", "standard deviation (σ)"]          # no Arabic: nothing to check
    assert g.wrong_meanings(good) == []
    assert g.wrong_meanings(["الانحراف (standard deviation)"]) == [
        "'standard deviation' explained as «الانحراف», glossary: «الانحراف المعياري»"]


def test_explain_moved_to_shared():
    from cb_shared.explain import INSTRUCTIONS, LanguageError, explain_language
    assert explain_language() == "mixed" and set(INSTRUCTIONS) == {"ar", "en", "mixed"}
    with pytest.raises(LanguageError):
        explain_language("fr")
