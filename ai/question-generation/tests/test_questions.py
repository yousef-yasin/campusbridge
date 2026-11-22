"""Practice questions with a fake engine: rules in the prompt, page links, checks, speech."""
from conftest import FakeEngine
from questions import QuestionConfig, QuestionGenerator, generate_questions, question_parts, questions_speech
from questions.__main__ import main
from cb_shared import TextUnit, UnitBlock

TEXT = [("heading", "Empirical Rule"),
        ("paragraph", "In a normal distribution about 68.27% of values lie within one standard deviation "
                      "of the mean, 95.45% within two and 99.73% within three."),
        ("paragraph", "Values beyond three standard deviations are often treated as outliers.")]
GOOD = {"questions": [
    {"question": "ما نسبة القيم التي تقع ضمن standard deviation واحد من mean؟", "answer": "حوالي 68.27%.", "block": "b2"},
    {"question": "متى تُعدّ القيمة outlier حسب السلايد؟", "answer": "إذا ابتعدت أكثر من ثلاثة standard deviations.",
     "block": "b3"}]}


def unit(number=17, blocks=TEXT):
    return TextUnit(number, "slide", [UnitBlock(f"b{i}", k, t) for i, (k, t) in enumerate(blocks, 1)], "Empirical Rule")


def gen(engine, language=None):
    return QuestionGenerator(QuestionConfig.from_env(), engine=engine, language=language)


def test_questions_with_answers_linked_to_the_page():
    engine = FakeEngine(GOOD)
    result = gen(engine).one(unit())
    assert result["status"] == "ok" and result["review"] == "draft"
    assert [(q["page"], q["unit_type"], q["block"]) for q in result["questions"]] == [(17, "slide", "b2"), (17, "slide", "b3")]
    prompt = engine.prompts[0]
    for rule in ("answerable from the text of this slide alone", "write fewer questions, or none",
                 "Never invent a question", "Copy numbers exactly"):
        assert rule in prompt
    assert questions_speech(result) == (
        "سؤال: ما نسبة القيم التي تقع ضمن standard deviation واحد من mean؟\nالجواب: حوالي 68.27%.\n\n"
        "سؤال: متى تُعدّ القيمة outlier حسب السلايد؟\nالجواب: إذا ابتعدت أكثر من ثلاثة standard deviations.")
    en = gen(FakeEngine({"questions": [{"question": "What share lies within one standard deviation?",
                                        "answer": "About 68.27%.", "block": "b2"}]}), "en").one(unit())
    assert question_parts(en) == [("Question: What share lies within one standard deviation?", "Answer: About 68.27%.")]


def test_no_question_when_the_page_is_not_enough_and_at_most_three():
    none = gen(FakeEngine({"questions": []})).one(unit())
    assert none["status"] == "ok" and none["questions"] == [] and questions_speech(none) == ""
    many = {"questions": [dict(GOOD["questions"][0]) for _ in range(5)]}
    other = unit(blocks=TEXT + [("paragraph", "A second example with more text for more questions.")])
    assert len(gen(FakeEngine(many)).one(other)["questions"]) == 3


def test_checks_mark_needs_review():
    bad = {"questions": [{"question": "ما نسبة القيم ضمن انحرافين؟", "answer": "95%، كما في Chebyshev theorem.",
                          "block": "b7"}]}
    result = gen(FakeEngine(bad)).one(unit())
    assert result["status"] == "needs_review"
    assert result["problems"] == ["numbers not in the slide: 95", "English words not in the slide: chebyshev, theorem",
                                  "answers linked to blocks that do not exist: b7"]


def test_skips_and_missing_key(capsys, tmp_path):
    engine = FakeEngine(GOOD)
    title = gen(engine).one(TextUnit(1, "slide", [UnitBlock("b1", "heading", "Chapter 2")]))
    assert title["status"] == "skipped" and engine.prompts == []
    results, warnings = generate_questions([unit(), unit(18)], QuestionConfig.from_env())      # real engine, no key
    assert [r["status"] for r in results] == ["unavailable", "unavailable"] and "GEMINI_API_KEY" in warnings[0]
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Empirical Rule"
    slide.placeholders[1].text = TEXT[1][1] + "\n" + TEXT[2][1]
    prs.save(str(tmp_path / "e.pptx"))
    assert main(["file", str(tmp_path / "e.pptx")]) == 0
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().err


def test_glossary_meaning_in_an_answer_is_checked():
    # Real case: CLT slide 7 (mixed), the answer translated sampling distribution wrongly.
    text = [("heading", "Central Limit Theorem"),
            ("paragraph", "The Central Limit Theorem is based on the idea of a sampling distribution: the probability "
                          "distribution of a statistic for a large number of random samples taken from a population.")]
    bad = {"questions": [{"question": "على ماذا تعتمد Central Limit Theorem؟",
                          "answer": "على فكرة sampling distribution (التوزيع العشوائي لعينة ما).", "block": "b2"}]}
    engine = FakeEngine(bad)
    result = gen(engine).one(unit(7, text))
    assert "- sampling distribution = توزيع المعاينة" in engine.prompts[0]
    assert result["status"] == "needs_review" and result["problems"][-1].startswith(
        "term meaning differs from the glossary: 'sampling distribution' explained as «التوزيع العشوائي لعينة ما»")
