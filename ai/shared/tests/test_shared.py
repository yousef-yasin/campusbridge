"""cb_shared: the Gemini text client (fake client), text units, checks and the review cache."""
import json
from types import SimpleNamespace

import pytest

from cb_shared import (AIBusyError, AIError, AILimitError, AIQuotaError, AIUnavailableError, GeminiText,
                       GeminiTextConfig, ReviewCache, TextUnit, UnitBlock, from_pages, from_transcript, merged,
                       missing_english, unverified_numbers)

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


class ApiError(Exception):
    def __init__(self, code, message="x"):
        super().__init__(message)
        self.code, self.message = code, message


class Client:
    """Answers per model: a list of errors/texts consumed in order."""

    def __init__(self, plan):
        self.plan, self.requests = {m: list(v) for m, v in plan.items()}, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.requests.append((model, config.response_json_schema))
        step = self.plan[model].pop(0)
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(text=step)


def engine(plan, tmp_path, **kw):
    (tmp_path / "k.env").write_text("GEMINI_API_KEY=FAKE-KEY-NOT-REAL\n", encoding="utf-8")
    cfg = GeminiTextConfig(models=tuple(plan), env_files=[str(tmp_path / "k.env")], retry_pauses=(0, 0), **kw)
    return GeminiText(cfg, client=Client(plan))


def test_busy_model_is_retried_then_the_next_model_is_used(tmp_path):
    ok = json.dumps({"summary": "ملخص"}, ensure_ascii=False)
    gen = engine({"a": [ApiError(503), ApiError(503), ApiError(503)], "b": [ok]}, tmp_path)
    assert gen.generate_json("p", SCHEMA) == {"summary": "ملخص"} and gen.last_model == "b"
    assert gen._client.requests == [("a", SCHEMA), ("a", SCHEMA), ("a", None), ("b", SCHEMA)]
    assert "used b" in gen.notes[0] and gen.calls == 4


def test_quota_moves_on_and_rejected_key_stops(tmp_path):
    ok = json.dumps({"summary": "x"})
    gen = engine({"a": [ApiError(429, "RESOURCE_EXHAUSTED")], "b": [ok]}, tmp_path)
    assert gen.generate_json("p", SCHEMA)["summary"] == "x"
    with pytest.raises(AIQuotaError):
        engine({"a": [ApiError(429)], "b": [ApiError(429)]}, tmp_path).generate_json("p", SCHEMA)
    gen = engine({"a": [ApiError(403, "key FAKE-KEY-NOT-REAL bad")], "b": [ok]}, tmp_path)
    with pytest.raises(AIUnavailableError) as err:
        gen.generate_json("p", SCHEMA)
    assert "FAKE-KEY-NOT-REAL" not in str(err.value) and len(gen._client.requests) == 1
    with pytest.raises(AIUnavailableError, match="unreachable"):
        engine({"a": [OSError("down")]}, tmp_path).generate_json("p", SCHEMA)
    with pytest.raises(AIBusyError):
        engine({"a": [ApiError(503)] * 3}, tmp_path).generate_json("p", SCHEMA)


def test_limit_missing_key_and_bad_answers(tmp_path, monkeypatch):
    with pytest.raises(AILimitError):
        engine({"a": ["{}"]}, tmp_path, max_calls=0).generate_json("p", SCHEMA)
    gen = GeminiText(GeminiTextConfig(env_files=[str(tmp_path / "none.env")]))
    with pytest.raises(AIUnavailableError, match="GEMINI_API_KEY is not set"):
        gen.generate_json("p", SCHEMA)
    with pytest.raises(AIError, match="missing summary"):
        engine({"a": ["{}"]}, tmp_path).generate_json("p", SCHEMA)
    listed = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
    assert engine({"a": ["[1, 2]"]}, tmp_path).generate_json("p", listed) == {"items": [1, 2]}
    monkeypatch.setenv("SUMMARY_MODELS", "m1, m2")
    monkeypatch.setenv("SUMMARY_MAX_CALLS", "7")
    cfg = GeminiTextConfig.from_env("SUMMARY")
    assert cfg.models == ("m1", "m2") and cfg.max_calls == 7


def test_units_from_document_pages_and_transcripts():
    block = lambda kind, text="", **kw: SimpleNamespace(kind=kind, text=text, items=kw.get("items"), image=kw.get("image"))
    page = SimpleNamespace(unit=16, unit_type="slide", sheet=None, blocks=[
        block("heading", "Z-Score"), block("paragraph", "A z-score of 0 means the mean."),
        block("list", "a\nb", items=["a", "b"]),
        block("image", image={"status": "described", "description": "منحنى طبيعي.", "text": "34.1%"}),
        block("image", image={"status": "decorative", "description": "زخرفة"}),
        block("references", "(1) Smith, 2020.")])
    unit = from_pages([page])[0]
    assert (unit.number, unit.unit_type, unit.title, unit.label) == (16, "slide", "Z-Score", "slide 16")
    assert [(b.id, b.kind) for b in unit.blocks] == [("b1", "heading"), ("b2", "paragraph"), ("b3", "list"),
                                                     ("b4", "image")]
    assert unit.blocks[3].text == "Image: منحنى طبيعي. Text in the image: 34.1%"
    assert unit.render().splitlines()[0] == "Title: Z-Score" and "[b3] (list) a\nb" in unit.render()
    parts = from_transcript([{"start": 0, "end": 5, "text": "مرحباً"}, {"start": 200, "end": 210, "text": "ثانياً"},
                             {"start": 320, "end": 330, "text": "ثالثاً"}], seconds_per_unit=300)
    assert [(u.number, u.unit_type, len(u.blocks), u.meta) for u in parts] == [
        (1, "part", 2, {"start": 0.0, "end": 210.0}), (2, "part", 1, {"start": 320.0, "end": 330.0})]


def test_title_unit_rule():
    unit = lambda *blocks: TextUnit(1, "slide", [UnitBlock(f"b{i}", k, t) for i, (k, t) in enumerate(blocks, 1)])
    assert unit(("heading", "Chapter 2"), ("paragraph", "Central Limit Theorem")).is_title_unit()
    assert not unit(("heading", "Intro"), ("paragraph", "We learn sampling today.")).is_title_unit()


def test_checks_and_cache(tmp_path):
    assert unverified_numbers(["يقع 94% من البيانات"], ["95.4% of the data"]) == ["94"]
    assert unverified_numbers(["أربعة وتسعون بالمائة"], ["95.4%"]) == ["94"]       # document-reader's check
    assert missing_english(["يوضح Central Limit Theorem و Sampling distribution"], "central limit theorem sampling") \
        == ["distribution"]
    assert missing_english(["the means of samples"], "The mean of a sample") == []    # plural forms are fine
    cache = ReviewCache(tmp_path)
    path = cache.path("ab" * 32, "m/1", "mixed", 2, "summary")
    assert path.name == "abababababababab__summary__m_1__mixed__v2.json"
    cache.save(path, {"result": {"summary": "a"}})
    assert cache.load(path)["review"] == "draft"
    assert merged({"summary": "a", "points": [1]}, {"summary": "b", "points": [], "note": "n"}) == \
        {"summary": "b", "points": [1]}
