import json

from conftest import FakeEngine
from assistant import Assistant
from assistant.evaluate import contains, failures, markdown, run, save, score
from cb_shared import AIBusyError


def test_contains_ignores_diacritics_spaces_and_compares_numbers():
    assert contains("الخطأ يساوي σ/√n", "σ / √n")
    assert contains("دُفعت فدية بقيمة 4.4 مليون دولار", "$4.4 million")
    assert contains("الاحتمال 40.03٪ تقريباً", "40.03%") and not contains("الاحتمال 40%", "40.03%")
    assert contains("طِباق الإيجاب", "طباق الايجاب")


QUESTIONS = {"version": 1, "questions": [
    {"id": "T1", "type": "text", "question": "When is the sampling distribution of the mean approximately normal?",
     "courses": ["STAT101"], "expected_status": "answered",
     "sources": [{"file": "CLT.pptx", "unit_type": "slide", "unit": 3}], "must_include": ["30"], "any_of": [["normal"]]},
    {"id": "F1", "type": "follow_up", "follows": "T1", "question": "And what does the histogram show?",
     "courses": ["STAT101"], "expected_status": "answered",
     "sources": [{"file": "CLT.pptx", "unit_type": "slide", "unit": 3}], "must_include": ["500"]},
    {"id": "N1", "type": "not_found", "question": "Who invented the telephone?", "courses": ["STAT101"],
     "expected_status": "not_found", "sources": [], "must_include": []},
    {"id": "P1", "type": "permission", "question": "كم تعيش أشجار الزيتون؟", "courses": ["STAT101"],
     "expected_status": "not_found", "sources": [], "must_include": [],
     "answer_in": [{"course": "AGR100", "file": "olive.docx", "unit_type": "page", "unit": 1}]},
]}


def test_run_scores_follow_ups_retries_and_permission(built, tmp_path):
    store, emb, cfg = built
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    calls = {"n": 0}

    def answer(prompt):
        calls["n"] += 1
        tag = "S1" if "[S1] file: CLT.pptx | slide 3" in prompt else "S2"
        text = (f"With a sample size of at least 30 it is approximately normal [{tag}]." if calls["n"] == 1 else
                f"It shows 500 sample means [{tag}].")
        return {"found": True, "sources": [tag], "answer": text}
    engine = FakeEngine(answer)
    busy = {"left": 1}
    real = engine.generate_json

    def flaky(prompt, schema):                    # the first request is "busy": retried, not an error
        if busy["left"]:
            busy["left"] -= 1
            raise AIBusyError("all models busy (503)")
        return real(prompt, schema)
    engine.generate_json = flaky
    result = run(path, lambda log: Assistant(store, emb, engine, cfg, language="en", log=log), retries=2, pause=0,
                 progress=lambda m: None)
    rows = {r["id"]: r for r in result["rows"]}
    assert rows["T1"]["attempts"] == 2 and rows["T1"]["status"] == "answered" and rows["T1"]["complete"]
    assert rows["T1"]["source_ok"] and rows["T1"]["hit5"]
    assert "Student: When is the sampling" in engine.prompts[-1]          # F1 asked in T1's conversation
    assert rows["F1"]["complete"] and rows["N1"]["decision_ok"] and rows["P1"]["decision_ok"]
    assert rows["P1"]["leak"] is False
    s = result["summary"]
    assert s["unavailable"] == 0 and s["decision_accuracy"] == 1.0 and s["refusal_recall"] == 1.0
    assert s["complete_answers"] == 1.0 and set(result["by_type"]) == {"text", "follow_up", "not_found", "permission"}
    paths = save(result, tmp_path / "results")
    assert "## By question type" in open(paths["markdown"], encoding="utf-8").read()
    assert json.load(open(paths["json"], encoding="utf-8"))["summary"] == s


def test_unavailable_is_counted_apart_and_failures_have_reasons():
    q = QUESTIONS["questions"][0]
    busy = score(q, {"status": "unavailable", "answer": "…", "notes": ["503"]})
    refused = score(q, {"status": "not_found", "answer": "هذا غير موجود في محاضرات المساق.", "notes":
                        ["no lecture chunk matches well enough: the text model was not called"],
                        "chunks": [{"file": "CLT.pptx", "unit": 2, "course": "STAT101", "similarity": 0.6, "coverage": 0.2}]})
    for r in (busy, refused):
        r["seconds"] = 1.0
    reasons = failures([busy, refused])
    assert [f["id"] for f in reasons] == ["T1"] and "refused before the model" in reasons[0]["reasons"][0]
    assert "correct page not in the first 5 chunks" in reasons[0]["reasons"][1]
    from assistant.evaluate import summarize
    s = summarize([busy, refused])
    assert s["unavailable"] == 1 and s["evaluated"] == 1 and s["decision_accuracy"] == 0.0
    assert "| Unavailable | 1 |" in markdown({"run": "x", "questions_file": "q", "questions_version": 1, "summary": s,
                                             "by_type": {"text": s}, "rows": [busy, refused]})


def test_a_glossary_term_also_matches_its_arabic_meaning():
    from cb_shared import load_glossary
    g = load_glossary()
    assert contains("قد يحتاج التشخيص إلى الخزعة", "biopsy", g) and not contains("قد يحتاج التشخيص إلى الخزعة", "biopsy")
    assert contains("يصبح الخطأ المعياري أصغر", "standard error", g)
    assert not contains("التوقيعات الرقمية", "digital signatures", g)            # not a glossary term: no rule
