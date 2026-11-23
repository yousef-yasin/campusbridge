import json

from conftest import FakeEmbedder, FakeEngine
from assistant import Assistant, HybridSearch, QALog
from cb_shared import AIQuotaError, AIUnavailableError, GeminiText, GeminiTextConfig


def tag(prompt, unit_label):
    """The excerpt tag the prompt gives to e.g. 'slide 3' (search order decides it)."""
    import re
    return re.search(r"\[(S\d+)\] file: [^|]+\| " + unit_label + r"(?!\d)", prompt).group(1)


def cite(text, unit_label="slide 3"):
    """An answer callable that cites the excerpt of unit_label."""
    return lambda prompt: {"found": True, "sources": [tag(prompt, unit_label)],
                           "answer": text.replace("[S]", f"[{tag(prompt, unit_label)}]")}


def make(built, *answers, error=None, embedder=None, summarize=None, language="mixed"):
    store, emb, cfg = built
    engine = FakeEngine(*answers, error=error)
    return Assistant(store, embedder or emb, engine, cfg, language=language, summarize=summarize), engine


# --- search ------------------------------------------------------------------------------
def test_arabic_question_finds_the_english_slide_through_the_glossary(built):
    store, _, cfg = built
    search = HybridSearch(store, None, Assistant._glossary(), cfg)          # words only
    found = search.search("ما هو توزيع المعاينة للمتوسط؟", ["STAT101"])
    assert found.hits[0].chunk.unit == 2 and found.confident
    assert "sampling distribution of the mean = توزيع المعاينة للمتوسط" in found.expansions


def test_keyword_search_ignores_diacritics_and_hamza_forms(built):
    store, _, cfg = built
    found = HybridSearch(store, None, None, cfg).search("كم تعيش اشجار الزيتون؟", ["AGR100"])
    assert found.hits[0].chunk.unit == 1 and found.confident


def test_only_the_students_courses_are_searched(built):
    store, emb, cfg = built
    found = HybridSearch(store, emb, None, cfg).search("olive trees", ["STAT101"])
    assert all(h.chunk.course == "STAT101" for h in found.hits) and not found.confident


def test_semantic_search_failure_falls_back_to_keywords(built):
    store, _, cfg = built
    found = HybridSearch(store, FakeEmbedder(fail=AIQuotaError("429")), None, cfg).search(
        "Central Limit Theorem sample size", ["STAT101"])
    assert found.hits[0].chunk.unit == 3 and "keyword search only" in found.notes[0]


# --- answers -----------------------------------------------------------------------------
def test_answer_cites_sources_and_is_ready_for_speech(built):
    a, engine = make(built, cite("عندما يكون حجم العينة 30 على الأقل يقترب توزيع المعاينة للمتوسط من "
                                 "normal distribution (التوزيع الطبيعي) [S]."))
    r = a.ask("متى يقترب توزيع المعاينة للمتوسط من التوزيع الطبيعي؟", ["STAT101"])
    assert r.status == "answered" and r.intent == "question" and r.problems == []
    assert r.answer.endswith("(التوزيع الطبيعي) [CLT.pptx، سلايد 3].")
    assert r.sources[0]["file"] == "CLT.pptx" and r.sources[0]["unit"] == 3 and r.sources[0]["blocks"] == ["b1", "b2", "b3"]
    assert r.speech.startswith("جواب تلقائي: عندما") and r.speech.endswith("المصادر: Sampling Distributions، سلايد 3.")
    assert "[" not in r.speech.split("المصادر")[0]
    assert 3 in [c["unit"] for c in r.chunks]
    prompt = engine.prompts[0]
    assert f"[{tag(prompt, 'slide 3')}] file: CLT.pptx | slide 3" in prompt and "normal distribution = التوزيع الطبيعي" in prompt
    assert "(image, image description) Image: A histogram" in prompt


def test_numbers_and_terms_not_in_the_chunks_need_review(built):
    a, _ = make(built, {"found": True, "sources": ["S1"],
                        "answer": "يكفي حجم عينة 25 حسب Chebyshev theorem [S1]."})
    r = a.ask("متى يقترب توزيع المعاينة للمتوسط من التوزيع الطبيعي؟", ["STAT101"])
    assert r.status == "needs_review"
    assert any("25" in p for p in r.problems) and any("chebyshev" in p for p in r.problems)
    assert "قد يحتاج هذا الجواب إلى مراجعة" in r.speech


def test_wrong_glossary_meaning_and_missing_source_need_review(built):
    a, _ = make(built, {"found": True, "sources": [],
                        "answer": "يقترب التوزيع من normal distribution (التوزيع العادي) عند حجم عينة كبير."})
    r = a.ask("متى يقترب توزيع المعاينة للمتوسط من التوزيع الطبيعي؟", ["STAT101"])
    assert r.status == "needs_review"
    assert any("glossary" in p for p in r.problems) and "the answer names no source" in r.problems


def test_weak_matches_answer_not_found_without_calling_the_model(built):
    a, engine = make(built, {"found": True, "sources": [], "answer": "x"})
    r = a.ask("من هو مخترع الهاتف؟", ["STAT101", "AGR100"])
    assert r.status == "not_found" and r.answer == "هذا غير موجود في محاضرات المساق."
    assert engine.prompts == [] and r.speech == "جواب تلقائي: هذا غير موجود في محاضرات المساق."


def test_model_saying_not_found_gives_the_stu20_message(built):
    a, engine = make(built, {"found": False, "answer": "", "sources": []})
    r = a.ask("What is the standard error of the sampling distribution of the mean?", ["STAT101"])
    assert engine.prompts and r.status == "not_found" and r.answer == "هذا غير موجود في محاضرات المساق."


def test_explain_slide_fetches_that_slide_directly(built):
    a, engine = make(built, {"found": True, "sources": ["S1"], "answer": "يشرح السلايد Central Limit Theorem [S1]."})
    r = a.ask("اشرح سلايد رقم ٣", ["STAT101"])
    assert r.intent == "slide" and r.status == "answered" and r.chunks[0]["methods"] == ["direct"]
    assert "explain slide 3 of CLT.pptx" in engine.prompts[0] and "[S2] file:" not in engine.prompts[0]
    missing = a.ask("اشرح سلايد 40", ["STAT101"])
    assert missing.status == "not_found" and len(engine.prompts) == 1


def test_summarise_the_lecture_uses_lecture_summarization(built):
    seen = {}

    def summarize(units, title):
        seen["units"], seen["title"] = [u.number for u in units], title
        return [], {"status": "ok", "summary": "المحاضرة عن توزيع المعاينة.", "problems": [], "model": "fake"}, []
    a, engine = make(built, summarize=summarize)
    r = a.ask("لخص المحاضرة", ["STAT101"])
    assert r.intent == "summary" and r.status == "answered" and r.answer == "المحاضرة عن توزيع المعاينة."
    assert seen == {"units": [2, 3], "title": "Sampling Distributions"} and engine.prompts == []   # no title slide
    assert [s["unit"] for s in r.sources] == [2, 3]
    both = a.ask("لخص المحاضرة", ["STAT101", "AGR100"])
    assert both.status == "clarify" and "CLT.pptx" in both.answer and "olive.docx" in both.answer


def test_summary_through_the_real_summarizer_module(built):
    page = {"summary": "يعرّف السلايد توزيع المعاينة للمتوسط.", "points": [], "terms": []}

    def answer(prompt):
        return {"summary": "ملف عن توزيع المعاينة للمتوسط."} if "Page summaries" in prompt else page
    a, engine = make(built, answer)
    r = a.ask("لخّص المحاضرة", ["STAT101"])
    assert r.intent == "summary" and r.answer == "ملف عن توزيع المعاينة للمتوسط." and r.status == "answered"


def test_explain_a_term_starts_with_the_glossary(built):
    a, engine = make(built, {"found": True, "sources": ["S1"],
                             "answer": "تستخدم المحاضرة Central Limit Theorem عندما يكون حجم العينة 30 على الأقل [S1]."})
    r = a.ask("اشرح مصطلح Central Limit Theorem", ["STAT101"])
    assert r.intent == "term" and r.answer.startswith("Central Limit Theorem: نظرية النهاية المركزية. تستخدم")
    assert r.sources[0]["type"] == "glossary" and r.sources[1]["unit"] == 3
    assert "القاموس المشترك" in r.speech
    only = a.ask("ما معنى ransomware؟", ["STAT101"])
    assert only.status == "answered" and only.answer.startswith("ransomware: برمجيات الفدية.") and len(engine.prompts) == 1


def test_follow_up_uses_the_last_exchanges(built):
    a, engine = make(built, {"found": True, "sources": ["S1"],
                             "answer": "حجم العينة 30 على الأقل [S1]."})
    first = a.ask("ما هي Central Limit Theorem؟", ["STAT101"])
    second = a.ask("وكم يجب أن يكون حجم العينة؟", ["STAT101"], first.conversation)
    assert "Student: ما هي Central Limit Theorem؟" in engine.prompts[1]
    assert second.status == "answered" and second.chunks[0]["unit"] == 3
    for i in range(4):
        a.ask(f"وما هو حجم العينة في Central Limit Theorem رقم {i}؟", ["STAT101"], first.conversation)
    assert engine.prompts[-1].count("Student:") == 3


def test_saved_questions_have_no_personal_data(built, tmp_path):
    a, _ = make(built, {"found": True, "sources": ["S1"], "answer": "حجم العينة 30 [S1]."})
    r = a.ask("كم حجم العينة في Central Limit Theorem؟", ["STAT101"])
    rows = json.loads((tmp_path / "qa-log" / "log.json").read_text(encoding="utf-8"))
    assert set(rows[0]) == set(QALog.FIELDS) | {"time"}
    assert rows[0]["conversation"] == r.conversation and len(r.conversation) == 12
    assert rows[0]["question"] == r.question and rows[0]["status"] == "answered"


def test_quota_and_missing_key_give_a_clear_message(built, tmp_path):
    a, _ = make(built, error=AIQuotaError("all models: 429"))
    r = a.ask("ما هي Central Limit Theorem؟", ["STAT101"])
    assert r.status == "unavailable" and "انتهت حصة الطلبات" in r.answer and r.speech == r.answer
    store, emb, cfg = built
    real = GeminiText(GeminiTextConfig(env_files=[str(tmp_path / "no.env")]))
    r = Assistant(store, emb, real, cfg).ask("ما هي Central Limit Theorem؟", ["STAT101"])
    assert r.status == "unavailable" and "مفتاح" in r.answer
    r = Assistant(store, emb, FakeEngine(error=AIUnavailableError("Gemini unreachable (internet required)")), cfg) \
        .ask("ما هي Central Limit Theorem؟", ["STAT101"])
    assert "لا يوجد اتصال بالإنترنت" in r.answer


def test_english_mode(built):
    a, _ = make(built, cite("With a sample size of at least 30 it is approximately normal [S]."), language="en")
    r = a.ask("When is the sampling distribution normal?", ["STAT101"])
    assert r.status == "answered" and r.answer.endswith("[CLT.pptx, slide 3].")
    assert r.speech.startswith("Automatic answer: With") and r.speech.endswith("Sources: Sampling Distributions, slide 3.")
    nothing = a.ask("Who invented the telephone?", ["STAT101"])
    assert nothing.answer == "This is not in the course lectures."


def test_cli_index_and_ask(tmp_path, capsys):
    import docx
    from assistant.__main__ import main
    path = tmp_path / "olive.docx"
    d = docx.Document()
    d.add_heading("شجرة الزيتون", 1)
    d.add_paragraph("تُزرع أشجار الزيتون في الأردن منذ آلاف السنين.")
    d.save(path)
    assert main(["index", str(path), "--course", "AGR100"]) == 0        # no key: words only, with a warning
    out = capsys.readouterr()
    assert "AGR100 / olive.docx: 1 units -> 1 chunks, 0 embedded" in out.out and "keyword search only" in out.err
    assert main(["courses"]) == 0 and "AGR100: olive.docx" in capsys.readouterr().out
    assert main(["ask", "من هو مخترع الهاتف؟", "--course", "AGR100", "--speech"]) == 0
    assert capsys.readouterr().out.strip() == "جواب تلقائي: هذا غير موجود في محاضرات المساق."
    assert main(["ask", "أين تزرع أشجار الزيتون؟", "--course", "AGR100"]) == 0     # needs the model: no key
    assert "مفتاح خدمة الذكاء الاصطناعي غير مضبوط" in capsys.readouterr().out


def test_spoken_sources_are_grouped_by_file_with_its_title():
    from assistant.speech import spoken_sources
    src = [{"type": "lecture", "file": "ch1_5e7c.pdf", "file_title": "Chapter 1", "unit": u, "unit_type": "page"}
           for u in (5, 6, 4, 5)] + [{"type": "lecture", "file": "x.pptx", "file_title": "", "unit": 2, "unit_type": "slide"},
                                     {"type": "glossary", "term": "integrity"}]
    assert spoken_sources(src, "mixed") == ["القاموس المشترك", "Chapter 1، صفحات 4 و5 و6", "x.pptx، سلايد 2"]
    assert spoken_sources(src, "en")[1] == "Chapter 1, pages 4, 5 and 6"
