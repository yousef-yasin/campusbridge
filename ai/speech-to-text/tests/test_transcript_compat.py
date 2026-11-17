"""Stage 1: transcript format stays byte-identical when glossary correction is disabled."""
from pathlib import Path

from stt import STTConfig
from stt.transcript import Segment, Transcript

FIX = Path(__file__).parent / "fixtures"


def _legacy():
    return Transcript([Segment(0.0, 3.5, "مرحبا بكم في المحاضرة"),
                       Segment(3.5, 7.25, "اليوم نتحدث عن Python", slide=2),
                       Segment(65.0, 70.0, "شو يعني خوارزمية؟")])


def test_disabled_output_is_byte_identical_to_legacy(tmp_path):
    out = _legacy().save(tmp_path / "t.txt")
    assert out.read_bytes() == (FIX / "legacy_transcript.txt").read_bytes()
    assert out.with_suffix(".json").read_bytes() == (FIX / "legacy_transcript.json").read_bytes()


def test_legacy_json_loads_without_new_fields():
    t = Transcript.load(FIX / "legacy_transcript.json")
    assert t.glossary is None
    assert all(s.raw_text is None and s.corrections is None for s in t.segments)
    assert t.segments[1].slide == 2


def test_enabled_fields_round_trip_exactly(tmp_path):
    raw = "لكي  تابت الالجوريثم\tحللنا"          # irregular whitespace must survive
    corr = [{"char_start": 10, "char_end": 20, "original": "الالجوريثم", "prefix": "ال",
             "term": "algorithm", "replacement": "الـ algorithm", "confidence": 1.0,
             "rule": "word_exact", "evidence": []}]
    t = Transcript([Segment(7.36, 14.36, "لكي  تابت الـ algorithm\tحللنا", slide=4,
                            raw_text=raw, corrections=corr),
                    Segment(14.36, 20.0, "اعتمدنا", raw_text="اعتمدنا", corrections=[])],
                   glossary={"course": "CS301", "version": 3, "sha256": "ab" * 32})
    p = t.save(tmp_path / "g.txt")
    back = Transcript.load(p.with_suffix(".json"))
    assert back.segments[0].raw_text == raw
    assert back.segments[0].corrections == corr
    assert back.segments[1].corrections == []          # [] preserved, not dropped
    assert back.glossary == t.glossary
    assert (back.segments[0].start, back.segments[0].end, back.segments[0].slide) == (7.36, 14.36, 4)
    import json
    data = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["raw_full_text"].startswith("لكي  تابت الالجوريثم")
    assert "algorithm" in data["full_text"]


def test_search_matches_raw_and_corrected_text():
    t = Transcript([Segment(0, 1, "الـ algorithm", raw_text="الالجوريثم", corrections=[])])
    assert len(t.search("algorithm")) == 1
    assert len(t.search("الالجوريثم")) == 1


def test_glossary_config(monkeypatch):
    assert STTConfig().glossary_path is None
    assert STTConfig.from_env().glossary_path is None
    monkeypatch.setenv("STT_GLOSSARY", "g.json")
    assert STTConfig.from_env().glossary_path == "g.json"
    assert STTConfig.from_env().for_live().glossary_path == "g.json"
