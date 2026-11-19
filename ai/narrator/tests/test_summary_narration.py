"""The narrator with page summaries and practice questions (fake engines), Arabic and English."""
import pytest

from conftest import NOW, config
from narrator import FileNarrator

PARAGRAPH = ("The Central Limit Theorem states that the distribution of sample means approaches a normal "
             "distribution as the sample size increases, when the sample size is at least 30.")
SUMMARY = {"summary": "تنص Central Limit Theorem على أن توزيع sample means يقترب من normal distribution.",
           "points": [{"text": "يحدث ذلك عندما يكون sample size على الأقل 30.", "block": "b2"}], "terms": []}
QUESTIONS = {"questions": [
    {"question": "ماذا يحدث لتوزيع sample means عندما يزداد sample size؟", "answer": "يقترب من normal distribution.",
     "block": "b2"},
    {"question": "ما أقل sample size مذكور؟", "answer": "30.", "block": "b2"}]}
FILE = {"summary": "يشرح الملف Central Limit Theorem."}


class FakeEngine:
    model = last_model = "fake-text"

    def __init__(self, *answers):
        self.answers, self.calls, self.notes = list(answers), 0, []

    def generate_json(self, prompt, schema):
        self.calls += 1
        return dict(self.answers[min(self.calls - 1, len(self.answers) - 1)])


@pytest.fixture
def deck(tmp_path):
    from pptx import Presentation
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = "Chapter 2"
    first.placeholders[1].text = "Central Limit Theorem"
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Central Limit Theorem"
    slide.placeholders[1].text = PARAGRAPH
    path = tmp_path / "deck.pptx"
    prs.save(str(path))
    return path


def jobs(lang):
    from narrator.files import ai_modules
    ai_modules()
    from questions import QuestionConfig, QuestionGenerator
    from summarizer import PageSummarizer, SummaryConfig
    summary_engine, question_engine = FakeEngine(SUMMARY, FILE), FakeEngine(QUESTIONS)
    return (PageSummarizer(SummaryConfig.from_env(), summary_engine, lang),
            QuestionGenerator(QuestionConfig.from_env(), question_engine, lang), summary_engine, question_engine)


def test_page_summary_is_read_after_the_page_and_on_request(deck):
    summarizer, questioner, s_engine, q_engine = jobs("mixed")
    narration = FileNarrator(config("mixed")).narrate(deck, {}, now=NOW, summarizer=summarizer, questioner=questioner)
    assert s_engine.calls == 2 and q_engine.calls == 1               # slide 1 is a title slide: skipped
    slide2 = narration.units[1]
    assert [s.kind for s in slide2][-1] == "page_summary"
    assert slide2[-1].text == ("ملخص تلقائي: تنص Central Limit Theorem على أن توزيع sample means يقترب من "
                               "normal distribution.\nالنقاط المهمة:\nيحدث ذلك عندما يكون sample size على الأقل 30.")
    assert all(s.kind != "page_summary" for s in narration.units[0])
    nav = narration.navigator()
    assert [s.text for s in nav.summarize()] == ["ملخص تلقائي للملف: يشرح الملف Central Limit Theorem."]   # intro
    nav.go_to(1)
    assert [s.text for s in nav.summarize()] == ["لا يوجد ملخص متاح هنا."]
    assert [s.text for s in nav.ask_me()] == ["لا توجد أسئلة متاحة هنا."]
    nav.go_to(2)
    assert nav.summarize()[0].text == slide2[-1].text
    first = nav.ask_me(wait_seconds=6)
    assert [(s.kind, s.text) for s in first] == [
        ("question", "سؤال: ماذا يحدث لتوزيع sample means عندما يزداد sample size؟"),
        ("wait", ""), ("answer", "الجواب: يقترب من normal distribution.")]
    assert first[1].position["seconds"] == 6 and first[0].position["questions"] == 2
    assert nav.ask_me()[0].text == "سؤال: ما أقل sample size مذكور؟"
    assert nav.ask_me()[0].text == first[0].text                     # starts again after the last one


def test_summaries_off_by_default_and_english_phrases(deck):
    plain = FileNarrator(config("en")).narrate(deck, {}, now=NOW)
    assert all(s.kind != "page_summary" for s in plain.segments)
    assert [s.text for s in plain.navigator().summarize()] == ["No summary is available here."]
    summarizer, questioner, _, _ = jobs("en")
    narration = FileNarrator(config("en")).narrate(deck, {}, now=NOW, summarizer=summarizer,
                                                   questioner=questioner, read_summaries=False)
    assert all(s.kind != "page_summary" for s in narration.segments)    # only on request
    nav = narration.navigator()
    nav.go_to(2)
    assert nav.summarize()[0].text.startswith("Automatic summary: ")
    assert [s.text for s in nav.ask_me()][::2] == ["Question: ماذا يحدث لتوزيع sample means عندما يزداد sample size؟",
                                                   "Answer: يقترب من normal distribution."]
