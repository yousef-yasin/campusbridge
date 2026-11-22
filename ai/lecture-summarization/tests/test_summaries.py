"""Page summaries with a fake engine: prompt rules, checks, cache, manual edits, speech."""
import json
from pathlib import Path

import pytest

from conftest import FakeEngine
from summarizer import (FileSummarizer, PageSummarizer, SummaryConfig, file_summary_speech, summarize_units,
                        summary_speech)
from summarizer.__main__ import main
from cb_shared import AIUnavailableError, TextUnit, UnitBlock
from summarizer.summarize import PROMPT_VERSION

TEXT = [("heading", "Z-Score"),
        ("paragraph", "A z-score describes the position of a value relative to the mean, measured in "
                      "standard deviations. A z-score of 0 means the value equals the mean."),
        ("list", "On a normal curve z-scores range from -3 to +3.\nAbout 95.4% of values lie within 2 standard deviations."),
        ("image", "Image: منحنى التوزيع الطبيعي. Text in the image: 34.1% 13.6% 2.1% 0.1%")]
GOOD = {"summary": "يشرح السلايد z-score (الدرجة المعيارية) وموقع القيمة بالنسبة إلى mean.",
        "points": [{"text": "z-score تساوي 0 تعني أن القيمة تساوي mean.", "block": "b2"},
                   {"text": "يقع حوالي 95.4% من القيم ضمن 2 standard deviations.", "block": "b3"}],
        "terms": [{"term": "z-score", "meaning": "موقع القيمة بالنسبة إلى المتوسط بوحدات الانحراف المعياري"}]}


def unit(number=16, blocks=TEXT, kind="slide"):
    return TextUnit(number, kind, [UnitBlock(f"b{i}", k, t) for i, (k, t) in enumerate(blocks, 1)], "Z-Score")


def summarizer(engine, language=None):
    return PageSummarizer(SummaryConfig.from_env(), engine=engine, language=language)


def test_summary_with_points_linked_to_blocks_and_mixed_language():
    engine = FakeEngine(GOOD)
    job = summarizer(engine)
    result = job.one(unit())
    assert result["status"] == "ok" and result["problems"] == [] and result["review"] == "draft"
    assert result["points"][1] == {"text": "يقع حوالي 95.4% من القيم ضمن 2 standard deviations.", "block": "b3"}
    prompt = engine.prompts[0]
    assert "Use ONLY the text of this slide" in prompt and "Copy every number exactly" in prompt
    assert "[b3] (list) On a normal curve" in prompt and "Title: Z-Score" in prompt
    assert "English term first and then its Arabic meaning" in prompt          # mixed (CB_EXPLAIN_LANGUAGE default)
    for mode, words in (("ar", "Translate technical terms"), ("en", "clear, simple English")):
        e = FakeEngine(GOOD)
        summarizer(e, mode).one(unit())
        assert words in e.prompts[0]


def test_checks_mark_needs_review():
    bad = dict(GOOD, summary="يقع 94% من القيم ضمن انحرافين، كما في Bayesian statistics.",
               points=[{"text": "نقطة", "block": "b9"}])
    result = summarizer(FakeEngine(bad)).one(unit())
    assert result["status"] == "needs_review"
    assert result["problems"] == ["numbers not in the slide: 94",
                                  "English words not in the slide: bayesian, statistics",
                                  "points linked to blocks that do not exist: b9"]
    en = dict(GOOD, summary="The slide explains how a value relates to the average.",
              terms=[{"term": "Bayes factor", "meaning": "x"}])
    assert summarizer(FakeEngine(en), "en").one(unit())["problems"] == ["English words not in the slide: bayes, factor"]


def test_title_slide_and_short_pages_are_skipped():
    engine = FakeEngine(GOOD)
    job = summarizer(engine)
    title = job.one(unit(1, [("heading", "Chapter 2"), ("paragraph", "Central Limit Theorem")]))
    short = job.one(unit(5, [("heading", "Outline"), ("paragraph", "What we will learn today.")]))
    assert (title["status"], title["reason"]) == ("skipped", "title slide")
    assert short["status"] == "skipped" and "too short" in short["reason"] and engine.prompts == []
    assert summary_speech(title) == ""


def test_cache_review_state_and_manual_edit_win(tmp_path):
    engine = FakeEngine(GOOD)
    first = summarizer(engine).one(unit())
    again = summarizer(engine).one(unit())
    assert len(engine.prompts) == 1 and again["cached"] and not first["cached"]
    path = Path(first["cache_file"])
    assert path.name.endswith(f"__summary__fake-text__mixed__v{PROMPT_VERSION}.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["review"] == "draft" and record["manual"]["summary"] == "" and record["result"] == GOOD
    record["review"] = "approved"
    record["manual"]["summary"] = "ملخص كتبه المدرّس."
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    edited = summarizer(engine).one(unit())
    assert (edited["status"], edited["review"], edited["summary"]) == ("manual", "approved", "ملخص كتبه المدرّس.")
    assert edited["points"] == GOOD["points"]                         # fields left empty stay automatic
    assert summary_speech(edited).startswith("ملخص: ملخص كتبه المدرّس.")
    changed = unit(blocks=TEXT[:3] + [("paragraph", "A new sentence was added to the slide text.")])
    summarizer(engine).one(changed)
    assert len(engine.prompts) == 2                                   # new text: new entry


def test_speech_and_file_summary():
    engine = FakeEngine(GOOD, {"summary": "يشرح الملف z-score و 95.4% من القيم."})
    results, whole, warnings = summarize_units([unit(), unit(17)], SummaryConfig.from_env(), engine, title="CLT")
    assert summary_speech(results[0]) == (
        "ملخص تلقائي: يشرح السلايد z-score (الدرجة المعيارية) وموقع القيمة بالنسبة إلى mean.\n"
        "النقاط المهمة:\n"
        "z-score تساوي 0 تعني أن القيمة تساوي mean.\n"
        "يقع حوالي 95.4% من القيم ضمن 2 standard deviations.\n"
        "المصطلحات:\n"
        "z-score: موقع القيمة بالنسبة إلى المتوسط بوحدات الانحراف المعياري.")
    assert whole["status"] == "ok" and whole["pages"] == [16, 17]
    titled = FileSummarizer(PageSummarizer(SummaryConfig.from_env(), FakeEngine({"summary": "يتناول Chapter 2 الموضوع."}),
                                           None)).summarize(results, [unit(), unit(17)], title="Chapter 2 - CLT")
    assert titled["status"] == "ok"                     # a word from the file title is not "outside" text
    assert file_summary_speech(whole) == "ملخص تلقائي للملف: يشرح الملف z-score و 95.4% من القيم."
    assert "[slide 16] يشرح السلايد" in engine.prompts[-1] and "Use ONLY these summaries" in engine.prompts[-1]
    en = dict(GOOD, summary="The slide explains z-scores.")
    r = summarizer(FakeEngine(en), "en").one(unit())
    assert summary_speech(r, points=False, terms=False) == "Automatic summary: The slide explains z-scores."


def test_no_key_is_a_warning_not_a_crash(capsys):
    results, whole, warnings = summarize_units([unit(), unit(17)], SummaryConfig.from_env())   # real engine
    assert [r["status"] for r in results] == ["unavailable", "unavailable"]
    assert "GEMINI_API_KEY is not set" in results[0]["reason"] and "stopped" in warnings[0]
    assert whole["status"] == "skipped"
    engine = FakeEngine(error=AIUnavailableError("Gemini unreachable (internet required)"))
    results, _, warnings = summarize_units([unit(), unit(17)], SummaryConfig.from_env(), engine)
    assert len(engine.prompts) == 1 and "unreachable" in results[1]["reason"]


def test_cli_on_a_generated_pptx(tmp_path, capsys):
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Z-Score"
    slide.placeholders[1].text = TEXT[1][1] + "\n" + TEXT[2][1]
    prs.save(str(tmp_path / "z.pptx"))
    assert main(["file", str(tmp_path / "z.pptx")]) == 0                # no key: warnings, exit 0
    captured = capsys.readouterr()
    assert "=== slide 1: unavailable" in captured.out and "GEMINI_API_KEY is not set" in captured.err


def test_glossary_meanings_in_the_prompt_and_checked():
    text = [("heading", "Sampling Distribution"),
            ("paragraph", "A sampling distribution is the probability distribution of a statistic over many "
                          "random samples drawn from a population, and it is the base of the Central Limit Theorem.")]
    engine = FakeEngine(dict(GOOD, summary="يشرح السلايد sampling distribution (التوزيع العشوائي لعينة ما).",
                             points=[{"text": "تعتمد Central Limit Theorem (نظرية النهاية المركزية) عليه.", "block": "b2"}],
                             terms=[]))
    result = summarizer(engine).one(unit(7, text))
    assert "- sampling distribution = توزيع المعاينة" in engine.prompts[0]
    assert "- Central Limit Theorem = نظرية النهاية المركزية" in engine.prompts[0]
    assert result["status"] == "needs_review" and result["problems"] == [
        "term meaning differs from the glossary: 'sampling distribution' explained as «التوزيع العشوائي لعينة ما», "
        "glossary: «توزيع المعاينة»"]
    fixed = FakeEngine(dict(GOOD, summary="يشرح السلايد sampling distribution (توزيع المعاينة).",
                            points=[{"text": "تعتمد عليه Central Limit Theorem.", "block": "b2"}], terms=[]))
    assert summarizer(fixed, "ar").one(unit(7, text + [("paragraph", "Second version of the slide text.")]))["status"] == "ok"
    en = FakeEngine(dict(GOOD, summary="The slide explains the sampling distribution.", points=[], terms=[]))
    summarizer(en, "en").one(unit(7, text + [("paragraph", "Third version of the text.")]))
    assert "Glossary:" not in en.prompts[0]                           # en mode: no Arabic meanings
