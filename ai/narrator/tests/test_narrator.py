"""Exact narrator output, in Arabic and English."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW, config, fake_describer
from narrator import (AssignmentNarrator, ChatNarrator, FileNarrator, InputError, NarratorConfig,
                      NotificationNarrator, QuizNarrator, public_quiz, speech_text)
from narrator.__main__ import main
from narrator.dates import say_duration, say_time, say_when
from narrator.words import count

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
META = {"course": "الإحصاء", "instructor": "د. ليال الزبن", "uploaded_at": "2026-11-15T10:00:00+03:00"}
IMAGE = {"category": "chart", "short_description": "منحنى Normal Distribution (التوزيع الطبيعي) لمتوسطات العينات.",
         "detailed_description": "تفصيل.", "text_in_image": "72"}


def texts(segments):
    return [s.text for s in segments]


def example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


# --- words, dates, times -----------------------------------------------------------------

def test_counting_dates_and_times():
    assert [count(n, "day", "ar") for n in (1, 2, 3, 10, 11, 25, 100, 103)] == \
        ["يوم واحد", "يومين", "3 أيام", "10 أيام", "11 يوماً", "25 يوماً", "100 يوم", "103 أيام"]
    assert count(1, "hour", "ar") == "ساعة واحدة" and count(1, "day", "en") == "1 day"
    tz = config().tz()
    assert say_when("2026-11-15T10:00:00+03:00", "ar", tz, NOW) == "الأحد 15 تشرين الثاني الساعة 10 صباحاً"
    assert say_when("2027-01-03", "ar", tz, NOW) == "الأحد 3 كانون الثاني 2027"
    assert say_when("2026-11-19T23:59", "ar", tz, NOW) == "غداً الساعة 11 و59 دقيقة مساءً"
    assert say_when("2026-11-19T23:59", "en", tz, NOW) == "tomorrow at 11:59 PM"
    times = [NOW.replace(hour=h, minute=m) for h, m in ((0, 0), (9, 30), (12, 15), (14, 0), (10, 45), (20, 5))]
    assert [say_time(t, "ar") for t in times] == [
        "الساعة 12 منتصف الليل", "الساعة 9 ونصف صباحاً", "الساعة 12 وربع ظهراً", "الساعة 2 بعد الظهر",
        "الساعة 11 إلا ربع صباحاً", "الساعة 8 و5 دقائق مساءً"]
    assert [say_time(t, "en") for t in times] == ["midnight", "9:30 AM", "12:15 PM", "2 PM", "10:45 AM", "8:05 PM"]
    assert [say_duration(timedelta(**d), "ar") for d in
            ({"days": 3}, {"hours": 2}, {"days": 1, "hours": 5}, {"minutes": 1}, {"seconds": 20})] == \
        ["3 أيام", "ساعتين", "يوم و5 ساعات", "دقيقة واحدة", "أقل من دقيقة"]
    assert say_duration(timedelta(days=1, hours=5), "en") == "1 day and 5 hours"


def test_guidance_language_follows_the_shared_setting(monkeypatch):
    for mode, phrases in (("ar", "ar"), ("mixed", "ar"), ("en", "en")):
        monkeypatch.setenv("CB_EXPLAIN_LANGUAGE", mode)
        assert NarratorConfig.from_env().phrase_language == phrases
    monkeypatch.setenv("CB_EXPLAIN_LANGUAGE", "fr")
    with pytest.raises(Exception, match="Unknown language"):
        NarratorConfig.from_env()


# --- files -------------------------------------------------------------------------------

AR_FILE = [
    "ملف من مساق الإحصاء، د. ليال الزبن. تاريخ الرفع: الأحد 15 تشرين الثاني الساعة 10 صباحاً، قبل 3 أيام. "
    "العنوان: مقدمة. النوع: عرض تقديمي PowerPoint من 3 سلايدات. يتناول موضوعين: مقدمة، Sampling. "
    "ويحتوي على صورة واحدة وجدول واحد. مدة الاستماع التقديرية حوالي دقيقة.",
    "الموضوع الأول من 2: مقدمة.",
    "سلايد 1 من 3.",
    "نتعلم اليوم توزيع المعاينة.",
    "الموضوع الثاني من 2: Sampling.",
    "سلايد 2 من 3.",
    "جدول من 3 أعمدة و5 صفوف. الأعمدة: Sample، Mean، Size.",
    "الصف 1 من 5: Sample: A; Mean: 71; Size: 36.",
    "الصف 2 من 5: Sample: B; Mean: 73; Size: 36.",
    "الصف 3 من 5: Sample: C; Mean: 72; Size: 30.",
    "لم تُقرأ بقية الصفوف، وعددها 2.",
    "سلايد 3 من 3: Sampling.",
    "صورة، وصف تلقائي: منحنى Normal Distribution (التوزيع الطبيعي) لمتوسطات العينات.",
    "انتهى الملف. الخيارات المتاحة: الاستماع من البداية، الرجوع إلى السلايد السابق، الذهاب إلى سلايد معيّن، "
    "أو الذهاب إلى موضوع معيّن.",
]
EN_FILE = [
    "A file from the course الإحصاء, د. ليال الزبن. Uploaded Sunday 15 November at 10 AM, 3 days ago. "
    "Title: مقدمة. Type: a PowerPoint presentation with 3 slides. It covers 2 topics: مقدمة, Sampling. "
    "It has 1 image and 1 table. Estimated listening time: about 1 minute.",
    "Topic 1 of 2: مقدمة.",
    "Slide 1 of 3.",
    "نتعلم اليوم توزيع المعاينة.",
    "Topic 2 of 2: Sampling.",
    "Slide 2 of 3.",
    "Table with 3 columns and 5 rows. Columns: Sample, Mean, Size.",
    "Row 1 of 5: Sample: A; Mean: 71; Size: 36.",
    "Row 2 of 5: Sample: B; Mean: 73; Size: 36.",
    "Row 3 of 5: Sample: C; Mean: 72; Size: 30.",
    "2 more rows are not read.",
    "Slide 3 of 3: Sampling.",
    "Image, automatic description: منحنى Normal Distribution (التوزيع الطبيعي) لمتوسطات العينات.",
    "End of file. Options: listen again from the beginning, go back to the previous slide, go to a slide, "
    "or go to a topic.",
]


@pytest.mark.parametrize("lang, expected", [("mixed", AR_FILE), ("en", EN_FILE)])
def test_file_narration_exact_text(lecture, lang, expected):
    narration = FileNarrator(config(lang, max_table_rows=3)).narrate(
        lecture, META, now=NOW, describer=fake_describer(IMAGE, lang))
    assert texts(narration.segments) == expected
    kinds = [s.kind for s in narration.segments]
    assert kinds == ["intro", "topic_change", "position", "content", "topic_change", "position", "table",
                     "table_row", "table_row", "table_row", "table", "position", "image", "outro"]
    row = narration.segments[8]
    assert row.position == {"unit": 2, "unit_type": "slide", "unit_count": 3, "topic": 2, "topic_count": 2,
                            "block": 1, "source": "file", "row": 2, "rows": 5}
    assert speech_text(narration.segments).startswith(expected[0] + "\n\n" + expected[1])


def test_missing_platform_information_is_left_out(lecture):
    narration = FileNarrator(config("ar", max_table_rows=10, number_rows_from=6)).narrate(lecture, {}, now=NOW)
    assert narration.intro.text == ("العنوان: مقدمة. النوع: عرض تقديمي PowerPoint من 3 سلايدات. "
                                    "يتناول موضوعين: مقدمة، Sampling. ويحتوي على صورة واحدة وجدول واحد. "
                                    "مدة الاستماع التقديرية حوالي دقيقة.")
    assert texts(narration.units[1])[3:] == ["Sample: A; Mean: 71; Size: 36.", "Sample: B; Mean: 73; Size: 36.",
                                             "Sample: C; Mean: 72; Size: 30.", "Sample: D; Mean: 70; Size: 40.",
                                             "Sample: E; Mean: 74; Size: 50."]     # short table: no "row 2 of 5"
    assert texts(narration.units[2]) == ["سلايد 3 من 3: Sampling.", "صورة بدون وصف."]   # not described
    only_course = FileNarrator(config("ar")).narrate(lecture, {"course": "الإحصاء"}, now=NOW)
    assert only_course.intro.text.startswith("ملف من مساق الإحصاء. العنوان: مقدمة.")


def test_table_in_an_image_without_a_header_row(lecture):
    # Real case, CLT slide 21: the model put the first z-table row in "columns".
    ztable = {"category": "table", "short_description": "جزء من جدول z.", "detailed_description": "",
              "text_in_image": "1.9 .9713 .9719 2.0 .9772 .9778",
              "table": {"columns": ["1.9", ".9713", ".9719"], "rows": [["2.0", ".9772", ".9778"]]}}
    narration = FileNarrator(config("ar")).narrate(lecture, {}, now=NOW, describer=fake_describer(ztable))
    assert texts(narration.units[2])[1:] == [
        "صورة، وصف تلقائي: جزء من جدول z.",
        "جدول من 3 أعمدة وصفين، بدون أسماء أعمدة.",
        "1.9، .9713، .9719.", "2.0، .9772، .9778."]
    assert narration.units[2][2].position["source"] == "image"


def _deck(tmp_path, first_slide_texts):
    from pptx import Presentation
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[0])          # title slide layout
    first.shapes.title.text = first_slide_texts[0]
    if len(first_slide_texts) > 1:
        first.placeholders[1].text = first_slide_texts[1]
    for title in ("Population and Samples", "Sampling Distribution"):
        prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = title
    path = tmp_path / "deck.pptx"
    prs.save(str(path))
    return path


def test_title_slide_is_not_a_topic(tmp_path):
    for texts_ in (["Chapter 2", "Central Limit Theorem"], ["Chapter 2"]):
        narration = FileNarrator(config("ar")).narrate(_deck(tmp_path, texts_), {}, now=NOW)
        assert "يتناول موضوعين: Population and Samples، Sampling Distribution." in narration.intro.text
        assert texts(narration.units[0])[0] == "سلايد 1 من 3: Chapter 2."           # no topic_change
        assert texts(narration.units[1])[0] == "الموضوع الأول من 2: Population and Samples."
    en = FileNarrator(config("en")).narrate(_deck(tmp_path, ["Chapter 2", "Central Limit Theorem"]), {}, now=NOW)
    assert "It covers 2 topics: Population and Samples, Sampling Distribution." in en.intro.text
    # a first slide that teaches (a full sentence) stays a topic
    teaching = FileNarrator(config("ar")).narrate(_deck(tmp_path, ["مقدمة", "نتعلم اليوم توزيع المعاينة."]), {}, now=NOW)
    assert "يتناول 3 مواضيع: مقدمة، Population and Samples، Sampling Distribution." in teaching.intro.text


def test_only_requested_units_have_their_images_described(three_slides_with_images):
    class Counting:
        model = "fake-vision"

        def __init__(self):
            self.calls = 0

        def describe(self, image, mime, prompt, schema):
            self.calls += 1
            return {"category": "chart", "short_description": "مخطط.", "detailed_description": "",
                    "text_in_image": ""}
    from reader import ImageDescriber, ReaderConfig
    engine = Counting()
    describer = ImageDescriber(ReaderConfig.from_env(), engine=engine)
    narration = FileNarrator(config("ar")).narrate(three_slides_with_images, {}, now=NOW, describer=describer, units={2})
    assert engine.calls == 1
    images = [s.text for unit in narration.units for s in unit if s.kind == "image"]
    assert images == ["صورة بدون وصف.", "صورة، وصف تلقائي: مخطط.", "صورة بدون وصف."]


def test_intro_counts_useful_images_and_listening_time_is_stable(lecture, monkeypatch):
    long_photo = {"category": "photo", "informative": True, "text_in_image": "", "detailed_description": "",
                  "short_description": " ".join(["كلمة"] * 400)}        # a very long description
    plain = FileNarrator(config("ar")).narrate(lecture, {}, now=NOW).intro.text
    described = FileNarrator(config("ar")).narrate(lecture, {}, now=NOW, describer=fake_describer(long_photo)).intro.text
    assert described == plain                       # same listening time, described or not
    assert "ويحتوي على صورة واحدة وجدول واحد. مدة الاستماع التقديرية حوالي دقيقة." in plain

    decorative = dict(long_photo, informative=False)
    intro = FileNarrator(config("ar")).narrate(                 # "ar": its own cache entry
        lecture, {}, now=NOW, describer=fake_describer(decorative, language="ar")).intro.text
    assert "ويحتوي على جدول واحد." in intro and "صورة" not in intro
    # the description is now in the cache: a later run without describing reads it, offline
    monkeypatch.setenv("READER_VISION_MODEL", "fake-vision")       # same cache key as the fake engine
    again = FileNarrator(config("ar")).narrate(lecture, {}, now=NOW)
    assert again.intro.text == intro and all(s.kind != "image" for s in again.segments)


def test_many_topics_name_the_first_five(tmp_path):
    from pptx import Presentation
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = "Statistics"   # title slide: not a topic
    for i in range(1, 9):
        prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = f"Topic {i}"
    prs.save(str(tmp_path / "t.pptx"))
    ar = FileNarrator(config("ar")).narrate(tmp_path / "t.pptx", {}, now=NOW).intro.text
    assert "يتناول 8 مواضيع: Topic 1، Topic 2، Topic 3، Topic 4، Topic 5، و3 مواضيع أخرى." in ar
    en = FileNarrator(config("en")).narrate(tmp_path / "t.pptx", {}, now=NOW).intro.text
    assert "It covers 8 topics: Topic 1, Topic 2, Topic 3, Topic 4, Topic 5, and 3 more." in en
    assert "ولا يحتوي على صور أو جداول" in ar and "It has no images or tables" in en


def test_navigation(lecture):
    nav = FileNarrator(config("ar")).narrate(lecture, META, now=NOW).navigator()
    assert texts(nav.where_am_i()) == ["الموضع الحالي: مقدمة الملف."]
    assert texts(nav.previous()) == ["هذه بداية الملف."]
    assert texts(nav.next())[:2] == ["الموضوع الأول من 2: مقدمة.", "سلايد 1 من 3."]
    assert texts(nav.go_to(3))[0] == "سلايد 3 من 3: Sampling."
    assert texts(nav.where_am_i()) == ["الموضع الحالي: سلايد 3 من 3، ضمن الموضوع الثاني من 2: Sampling."]
    assert texts(nav.repeat())[0] == "سلايد 3 من 3: Sampling."
    assert texts(nav.previous())[1] == "سلايد 2 من 3."
    assert texts(nav.go_to_topic(1))[0] == "الموضوع الأول من 2: مقدمة."
    assert texts(nav.go_to(9)) == ["الرقم 9 غير موجود، والملف فيه 3 سلايدات."]
    assert texts(nav.go_to_topic(5)) == ["الموضوع رقم 5 غير موجود، والملف فيه موضوعين."]
    nav.go_to(3)
    assert texts(nav.next())[0].startswith("انتهى الملف.")
    assert texts(nav.next()) == ["هذه نهاية الملف."]
    assert texts(nav.where_am_i()) == ["الموضع الحالي: نهاية الملف."]
    en = FileNarrator(config("en")).narrate(lecture, META, now=NOW).navigator()
    en.go_to(2)
    assert texts(en.where_am_i()) == ["Current position: slide 2 of 3, in topic 2 of 2: Sampling."]
    assert texts(en.go_to(9)) == ["There is no slide 9; the file has 3 slides."]


# --- quiz --------------------------------------------------------------------------------

def test_quiz_exact_text_arabic():
    quiz = QuizNarrator(example("quiz"), config("ar"), NOW)
    assert texts(quiz.intro()) == [
        "كويز: Quiz 2: Central Limit Theorem. مساق الإحصاء. يحتوي على 3 أسئلة. المدة: 15 دقيقة. "
        "المحاولات المسموحة: محاولة واحدة. المحاولات المتبقية: محاولة واحدة. "
        "الموعد: يُغلق غداً الساعة 11 و59 دقيقة مساءً، باقي يوم و11 ساعة."]
    assert texts(quiz.question(1)) == [
        "سؤال 1 من 3.", "اختيار من متعدد، العلامة: 2.",
        "According to the Central Limit Theorem, the sampling distribution of the mean becomes approximately "
        "normal when:",
        "الخيار أ: The sample size is large (n ≥ 30).", "الخيار ب: The population is always normal.",
        "الخيار ج: The sample size is 5.", "الخيار د: The standard deviation is zero."]
    assert texts(quiz.question(2))[1:] == [
        "صح أو خطأ، العلامة: 1.",
        "حسب القاعدة التجريبية، يقع حوالي 95% من البيانات ضمن انحرافين معياريين من المتوسط.",
        "الخيار أ: صح.", "الخيار ب: خطأ."]
    assert texts(quiz.question(3))[1:] == [
        "إجابة قصيرة، العلامة: 3.", "If μ = 72, σ = 3 and n = 36, what is the standard error of the mean?",
        "الإجابة كتابةً."]
    assert texts(quiz.confirm(1, "ب")) == [
        "الإجابة المختارة للسؤال 1: الخيار ب: The population is always normal. هل يتم إرسال هذه الإجابة؟"]
    assert texts(quiz.confirm(2, True)) == ["الإجابة المختارة للسؤال 2: الخيار أ: صح. هل يتم إرسال هذه الإجابة؟"]
    assert texts(quiz.confirm(3, "0.5")) == ["الإجابة المكتوبة للسؤال 3: 0.5. هل يتم إرسال هذه الإجابة؟"]
    assert texts(quiz.confirm(3, "")) == ["لا توجد إجابة للسؤال 3 بعد."]
    assert texts(quiz.confirm_submit({1: 0, 2: True})) == [
        "عدد الأسئلة المجاب عنها: 2 من 3. بدون إجابة: السؤال 3. هل يتم إرسال الكويز؟"]
    assert texts([quiz.time_warning(5), quiz.time_warning(1)]) == [
        "تنبيه: باقي 5 دقائق على انتهاء الكويز.", "تنبيه: باقي دقيقة واحدة على انتهاء الكويز."]


def test_quiz_exact_text_english():
    quiz = QuizNarrator(example("quiz"), config("en"), NOW)
    assert texts(quiz.intro()) == [
        "Quiz: Quiz 2: Central Limit Theorem. Course: الإحصاء. It has 3 questions. Time limit: 15 minutes. "
        "Attempts allowed: 1. Attempts left: 1. Deadline: closes tomorrow at 11:59 PM, 1 day and 11 hours left."]
    assert texts(quiz.question(2))[:2] == ["Question 2 of 3.", "True or false, 1 point."]
    assert texts(quiz.question(2))[3:] == ["Option A: True.", "Option B: False."]
    assert texts(quiz.question(1))[3] == "Option A: The sample size is large (n ≥ 30)."
    assert texts(quiz.confirm(1, "C")) == [
        "Selected answer for question 1: option C: The sample size is 5. Submit this answer?"]
    assert texts(quiz.confirm_submit({})) == [
        "Answered questions: 0 of 3. Without an answer: questions 1, 2, 3. Submit the quiz?"]
    assert quiz.time_warning(5).text == "Warning: 5 minutes left in the quiz."


def test_correct_answer_is_never_read():
    data = example("quiz")
    data["answer_key"] = {"1": "SECRET-KEY-1"}
    data["questions"][0]["options"][0]["feedback"] = "SECRET-FEEDBACK"
    data["questions"][0]["correct_option"] = 0
    data["questions"][1]["solution"] = "SECRET-SOLUTION"
    data["questions"][2]["correct_answer"] = "SECRET-ANSWER-0.5"
    data["questions"][2]["answer_key"] = "SECRET-ANSWER-0.5"
    secrets = ["SECRET", "0.5", "With n of at least 30", "σ/√n"]
    for lang in ("ar", "en", "mixed"):
        quiz = QuizNarrator(data, config(lang), NOW)
        said = quiz.all_segments() + quiz.confirm_submit({}) + [quiz.time_warning(5)]
        for n in (1, 2):
            for answer in range(len(quiz._options(quiz.questions[n - 1]))):
                said += quiz.confirm(n, answer)
        said += quiz.confirm(3, "my answer")
        text = speech_text(said) + json.dumps([s.position for s in said], ensure_ascii=False)
        for secret in secrets:
            assert secret not in text
        for word in ("correct", "Correct", "صحيح", "الإجابة الصحيحة"):
            assert word not in text
    kept = public_quiz(data)
    assert set(kept) == {"title", "course", "duration_minutes", "attempts_allowed", "attempts_used",
                         "opens_at", "closes_at", "questions"}
    assert all(set(q) == {"type", "points", "text", "options"} for q in kept["questions"])
    assert kept["questions"][0]["options"][0] == "The sample size is large (n ≥ 30)"


def test_quiz_time_warnings_are_said_once():
    quiz = QuizNarrator(example("quiz"), config("ar"), NOW)
    end = NOW + timedelta(minutes=20)
    assert quiz.warnings_due(end, NOW) == []
    assert texts(quiz.warnings_due(end, NOW + timedelta(minutes=15, seconds=10))) == ["تنبيه: باقي 5 دقائق على انتهاء الكويز."]
    assert quiz.warnings_due(end, NOW + timedelta(minutes=16)) == []
    assert texts(quiz.warnings_due(end, NOW + timedelta(minutes=19, seconds=5))) == ["تنبيه: باقي دقيقة واحدة على انتهاء الكويز."]
    assert quiz.warnings_due(end, NOW + timedelta(minutes=19, seconds=30)) == []


def test_bad_quiz_input_is_reported():
    with pytest.raises(InputError, match="questions"):
        QuizNarrator({"title": "x"}, config(), NOW)
    with pytest.raises(InputError, match="unknown type"):
        QuizNarrator({"questions": [{"type": "essay", "text": "q"}]}, config(), NOW)
    with pytest.raises(InputError, match="not one of the options"):
        QuizNarrator(example("quiz"), config(), NOW).confirm(1, "ي")


# --- assignment, chat, notifications -------------------------------------------------------

def test_assignment_exact_text():
    assert texts(AssignmentNarrator(config("ar"), NOW).narrate(example("assignment"))) == [
        "واجب: Homework 3: Sampling Distributions. مساق الإحصاء.",
        "الموعد: السبت 21 تشرين الثاني الساعة 11 و59 دقيقة مساءً، باقي 3 أيام.",
        "الوصف: Solve the three exercises at the end of Chapter 2 and show your steps. Upload one PDF file.",
        "يحتوي الواجب على مرفقين: Homework3.pdf، z-table.pdf.",
        "حالة التسليم: لم يُسلَّم بعد."]
    assert texts(AssignmentNarrator(config("en"), NOW).narrate(example("assignment"))) == [
        "Assignment: Homework 3: Sampling Distributions. Course: الإحصاء.",
        "Due Saturday 21 November at 11:59 PM, 3 days left.",
        "Description: Solve the three exercises at the end of Chapter 2 and show your steps. Upload one PDF file.",
        "2 attachments: Homework3.pdf, z-table.pdf.",
        "Submission: not submitted yet."]
    graded = {"title": "HW1", "due_at": "2026-11-16T23:59:00+03:00", "attachments": [],
              "submission": {"status": "graded", "grade": 18, "max_grade": 20}}
    assert texts(AssignmentNarrator(config("ar"), NOW).narrate(graded)) == [
        "واجب: HW1.", "الموعد: الاثنين 16 تشرين الثاني الساعة 11 و59 دقيقة مساءً، انتهى الموعد منذ يوم و12 ساعة.",
        "بدون مرفقات.", "حالة التسليم: تم التسليم والتصحيح، العلامة 18 من 20."]
    late = {"title": "HW1", "submission": {"status": "late", "submitted_at": "2026-11-17T08:00:00+03:00"}}
    assert texts(AssignmentNarrator(config("en"), NOW).narrate(late))[1] == \
        "Submission: submitted late yesterday at 8 AM."


def test_chat_exact_text():
    messages = example("chat")
    assert texts(ChatNarrator(config("ar"), NOW).messages(messages)) == [
        "عندك 3 رسائل جديدة.",
        "الرسالة 1 من 3: من د. ليال الزبن، من هيئة التدريس، اليوم الساعة 9 ونصف صباحاً. "
        "نص الرسالة: تم رفع حل الواجب الثاني على صفحة المساق. تحتوي على مرفق واحد: HW2-solution.pdf.",
        "الرسالة 2 من 3: من أحمد خالد، من الطلبة، اليوم الساعة 10 و5 دقائق صباحاً. نص الرسالة: Is the quiz open book?",
        "الرسالة 3 من 3: من سارة يوسف، من فريق التدريس، أمس الساعة 6 مساءً. "
        "نص الرسالة: ساعات المكتب يوم الأربعاء من 12 إلى 2."]
    assert texts(ChatNarrator(config("en"), NOW).messages(messages[:1])) == [
        "Message from د. ليال الزبن, instructor, today at 9:30 AM. "
        "Message: تم رفع حل الواجب الثاني على صفحة المساق. 1 attachment: HW2-solution.pdf."]
    assert texts(ChatNarrator(config("ar"), NOW).messages(messages[:2]))[0] == "عندك رسالتين جديدتين."
    assert ChatNarrator(config("en"), NOW).messages(messages)[0].text == "You have 3 new messages."
    assert texts(ChatNarrator(config("ar"), NOW).messages([{"text": "مرحبا"}])) == ["رسالة. نص الرسالة: مرحبا."]


AR_NOTIFICATIONS = [
    "عندك 6 إشعارات جديدة. تنبيهات الطوارئ أولاً.",
    "الإشعار 1 من 6. تنبيه طوارئ: يجب إخلاء مبنى كلية العلوم فوراً بسبب إنذار حريق. المكان: مبنى كلية العلوم. "
    "التعليمات: التوجه إلى الساحة الرئيسية عبر أقرب مخرج، وعدم استخدام المصاعد. "
    "وقت الإشعار: اليوم الساعة 11 و55 دقيقة صباحاً.",
    "الإشعار 2 من 6. تذكير بمحاضرة: مساق الإحصاء، اليوم الساعة 12 ونصف ظهراً، بعد 30 دقيقة، في القاعة 204.",
    "الإشعار 3 من 6. تغيير قاعة: محاضرة مساق الإحصاء، غداً الساعة 10 صباحاً، بعد 22 ساعة، "
    "انتقلت من القاعة 204 إلى القاعة 310.",
    "الإشعار 4 من 6. تذكير بكويز: Quiz 2: Central Limit Theorem، مساق الإحصاء، "
    "يُغلق غداً الساعة 11 و59 دقيقة مساءً، باقي يوم و11 ساعة.",
    "الإشعار 5 من 6. موعد تسليم واجب: Homework 3: Sampling Distributions، مساق الإحصاء، "
    "الموعد السبت 21 تشرين الثاني الساعة 11 و59 دقيقة مساءً، باقي 3 أيام.",
    "الإشعار 6 من 6. مشكلة تقنية: رفع الملفات على المنصة متوقف مؤقتاً. الخدمة المتأثرة: رفع الواجبات. "
    "الحل المتوقع: اليوم الساعة 3 بعد الظهر.",
]


def test_notifications_emergency_first_exact_text():
    segments = NotificationNarrator(config("ar"), NOW).notifications(example("notifications"))
    assert texts(segments) == AR_NOTIFICATIONS
    assert [s.kind for s in segments] == ["summary", "emergency"] + ["notification"] * 5
    assert segments[1].position["priority"] == "high"
    en = NotificationNarrator(config("en"), NOW).notifications(example("notifications"))
    assert texts(en)[0] == "You have 6 new notifications. Emergency alerts first."
    assert texts(en)[2] == ("Notification 2 of 6. Lecture reminder: الإحصاء lecture, today at 12:30 PM, "
                            "in 30 minutes, in room 204.")
    assert texts(en)[6] == ("Notification 6 of 6. Technical issue: رفع الملفات على المنصة متوقف مؤقتاً. "
                            "Affected service: رفع الواجبات. Expected fix: today at 3 PM.")
    one = NotificationNarrator(config("ar"), NOW).notifications([{"type": "room_change", "new_room": "310"}])
    assert texts(one) == ["تغيير قاعة: محاضرة، أصبحت في القاعة 310."]
    with pytest.raises(InputError, match="type"):
        NotificationNarrator(config(), NOW).notifications([{"type": "party"}])


# --- CLI ---------------------------------------------------------------------------------

def test_cli_runs_each_example(lecture, capsys):
    now = "--now=2026-11-18T12:00:00+03:00"
    for args in (["quiz", str(EXAMPLES / "quiz.json"), "--question", "1"],
                 ["assignment", str(EXAMPLES / "assignment.json")], ["chat", str(EXAMPLES / "chat.json")],
                 ["notifications", str(EXAMPLES / "notifications.json")],
                 ["file", str(lecture), "--meta", str(EXAMPLES / "file-meta.json"), "--units", "2"]):
        assert main([now] + args) == 0
    out = capsys.readouterr().out
    assert "[position] سؤال 1 من 3." in out and "[emergency] الإشعار 1 من 6." in out
    assert "[position] سلايد 2 من 3." in out and "سلايد 1 من 3" not in out
    assert main(["--json", "--lang", "en", now, "quiz", str(EXAMPLES / "quiz.json"), "--warning", "5"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"text": "Warning: 5 minutes left in the quiz.", "kind": "time_warning", "position": {"minutes_left": 5}}]
    assert main(["quiz", str(lecture)]) == 2 and "not valid JSON" in capsys.readouterr().err
