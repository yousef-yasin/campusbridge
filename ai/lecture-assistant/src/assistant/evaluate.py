"""Evaluation: run eval/questions.json through the assistant and measure it.

Per question:
- expected status (answered / not_found) against the actual one;
- Hit@1 / Hit@5: is the correct page or slide the first, or among the first 5, retrieved chunks;
- complete: every must_include item and one item of every any_of group is in the answer
  (no diacritics, case and spaces ignored; an item with digits matches when its numbers are in
  the answer, by value; an item that is a term of the shared glossary also matches its Arabic
  meaning or an accepted wording, since ar/mixed answers translate terms);
- cited: the sources named in the answer include the correct page or slide;
- needs_review, time, attempts.
"unavailable" (busy, quota, no internet) is retried, and when it stays it is counted apart, not as
an error. Follow-up questions are asked in the conversation of the question they follow.
Nothing in the assistant's settings is changed by the evaluation.
"""
import json
import re
import tempfile
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .arabic import normalize
from .history import QALog

ANSWERED = ("answered", "needs_review")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", normalize(text or "").replace("٫", ".").replace("−", "-"))


def _numbers(text: str) -> List[float]:
    out = []
    for n in _NUMBER.findall(normalize(text or "")):
        try:
            out.append(float(n.replace(",", "")))
        except ValueError:
            continue
    return out


def contains(answer: str, item: str, glossary=None) -> bool:
    """True when the answer has the item: as text, for an item with digits all its numbers, and for a
    glossary term its Arabic meaning (or an accepted wording)."""
    if _plain(item) in _plain(answer):
        return True
    entry = glossary.entries.get(item.strip().lower()) if glossary is not None else None
    if entry is not None and entry.matches(answer):
        return True
    wanted = _numbers(item)
    if wanted:
        have = _numbers(answer)
        return all(any(abs(w - h) < 1e-9 for h in have) for w in wanted)
    return False


def _same(source: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    return source.get("file") == expected.get("file") and source.get("unit") == expected.get("unit")


def score(q: Dict[str, Any], answer: Dict[str, Any], glossary=None) -> Dict[str, Any]:
    status = answer["status"]
    expected = q["expected_status"]
    row: Dict[str, Any] = {"id": q["id"], "type": q["type"], "question": q["question"], "courses": q["courses"],
                           "expected_status": expected, "status": status, "intent": answer.get("intent"),
                           "answer": answer.get("answer", ""), "needs_review": status == "needs_review",
                           "problems": answer.get("problems", []), "notes": answer.get("notes", [])}
    if status == "unavailable":
        row["unavailable"] = True
        return row
    row["unavailable"] = False
    actual = "answered" if status in ANSWERED else status
    row["decision_ok"] = actual == expected
    chunks = answer.get("chunks") or []
    row["retrieved"] = [{"file": c["file"], "unit": c["unit"], "similarity": c.get("similarity"),
                         "coverage": c.get("coverage")} for c in chunks]
    sims = [c.get("similarity") for c in chunks if c.get("similarity") is not None]
    row["best_similarity"] = max(sims) if sims else None
    row["best_coverage"] = max((c.get("coverage") or 0 for c in chunks), default=0.0)
    if q.get("answer_in"):
        row["leak"] = any(c.get("course") in {a["course"] for a in q["answer_in"]} for c in chunks)
    if expected != "answered":
        return row
    sources = q["sources"]
    ranks = [i for i, c in enumerate(chunks) if any(_same(c, s) for s in sources)]
    row["hit1"] = bool(ranks) and ranks[0] == 0
    row["hit5"] = bool(ranks) and ranks[0] < 5
    row["rank"] = ranks[0] + 1 if ranks else None
    text = answer.get("answer", "")
    missing = [m for m in q.get("must_include", []) if not contains(text, m, glossary)]
    missing += [" | ".join(g) for g in q.get("any_of", []) if not any(contains(text, a, glossary) for a in g)]
    row["missing"] = missing
    row["complete"] = actual == "answered" and not missing
    cited = [s for s in answer.get("sources") or [] if s.get("type") == "lecture"]
    row["cited"] = [f"{s.get('file')} {s.get('unit_type')} {s.get('unit')}" for s in cited]
    row["source_ok"] = actual == "answered" and any(_same(s, e) for s in cited for e in sources)
    return row


def _rate(rows, key) -> Optional[float]:
    values = [r[key] for r in rows if key in r]
    return round(sum(1 for v in values if v) / len(values), 3) if values else None


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [r for r in rows if not r.get("unavailable")]
    answerable = [r for r in done if r["expected_status"] == "answered"]
    refused = [r for r in done if r["status"] == "not_found"]
    should_refuse = [r for r in done if r["expected_status"] == "not_found"]
    times = [r["seconds"] for r in done if r.get("seconds") is not None]
    return {
        "questions": len(rows), "evaluated": len(done), "unavailable": len(rows) - len(done),
        "decision_accuracy": _rate(done, "decision_ok"),
        "refusal_precision": round(sum(r["expected_status"] == "not_found" for r in refused) / len(refused), 3) if refused else None,
        "refusal_recall": round(sum(r["status"] == "not_found" for r in should_refuse) / len(should_refuse), 3) if should_refuse else None,
        "hit_at_1": _rate(answerable, "hit1"), "hit_at_5": _rate(answerable, "hit5"),
        "complete_answers": _rate(answerable, "complete"),
        "correct_sources": _rate([r for r in answerable if r["status"] in ANSWERED], "source_ok"),
        "needs_review": sum(r["needs_review"] for r in done),
        "mean_seconds": round(sum(times) / len(times), 1) if times else None,
        "leaks": sum(1 for r in done if r.get("leak")),
    }


def run(questions_path, assistant_factory: Callable[[QALog], Any], retries: int = 3, pause: float = 30.0,
        progress: Callable[[str], None] = print) -> Dict[str, Any]:
    """Ask every question; assistant_factory(log) builds the assistant with a throw-away log."""
    data = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    questions = data["questions"]
    rows: List[Dict[str, Any]] = []
    conversations: Dict[str, str] = {}
    from cb_shared import GlossaryError, load_glossary
    try:
        glossary = load_glossary()
    except GlossaryError:
        glossary = None
    with tempfile.TemporaryDirectory() as tmp:
        assistant = assistant_factory(QALog(Path(tmp) / "log.json"))
        for q in questions:
            conversation = conversations.get(q.get("follows")) if q.get("follows") else None
            if q.get("follows") and conversation is None:
                progress(f"{q['id']}: the question it follows ({q['follows']}) has no conversation")
            attempts, answer, seconds = 0, None, None
            while True:
                attempts += 1
                start = time.time()
                result = assistant.ask(q["question"], q["courses"], conversation)
                seconds = round(time.time() - start, 1)
                answer = result.to_dict()
                if answer["status"] != "unavailable" or attempts > retries:
                    break
                progress(f"{q['id']}: unavailable ({'; '.join(answer.get('notes') or [])[:120]}), retry in {pause:.0f} s")
                time.sleep(pause)
                # a retry starts again; a follow-up keeps its conversation (the failed turn is in it)
            conversations[q["id"]] = answer["conversation"]
            row = score(q, answer, glossary)
            row.update(seconds=seconds, attempts=attempts, model=answer.get("model"))
            rows.append(row)
            progress(f"{q['id']} [{q['type']}] expected {q['expected_status']}, got {answer['status']} "
                     f"({seconds} s, {attempts} attempt{'s' if attempts > 1 else ''})")
    by_type = OrderedDict()
    for kind in dict.fromkeys(r["type"] for r in rows):
        by_type[kind] = summarize([r for r in rows if r["type"] == kind])
    return {"run": datetime.now().isoformat(timespec="seconds"), "questions_file": str(questions_path),
            "questions_version": data.get("version"),
            "glossary": glossary.info if glossary is not None else None, "summary": summarize(rows), "by_type": by_type, "rows": rows}


def _pct(v) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


def failures(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if r.get("unavailable"):
            continue
        reasons = []
        if not r["decision_ok"]:
            if r["expected_status"] == "answered":
                if r["status"] == "not_found" and any("not called" in n for n in r["notes"]):
                    reasons.append(f"refused before the model: best similarity {r['best_similarity']}, "
                                   f"best coverage {r['best_coverage']}, below the thresholds")
                elif r["status"] == "not_found":
                    reasons.append("the model said the chunks do not answer")
                else:
                    reasons.append(f"status {r['status']}")
            else:
                reasons.append("answered although the answer is not in the allowed lectures")
        if r["expected_status"] == "answered":
            if not r.get("hit5"):
                reasons.append("correct page not in the first 5 chunks" + (f" (rank {r['rank']})" if r.get("rank") else ""))
            if r["status"] in ANSWERED and r.get("missing"):
                reasons.append("missing: " + "; ".join(r["missing"]))
            if r["status"] in ANSWERED and not r.get("source_ok"):
                reasons.append("correct page not cited (cited: " + ", ".join(r.get("cited") or ["none"]) + ")")
        if r.get("leak"):
            reasons.append("retrieved a chunk from a course the student does not take")
        if reasons:
            out.append({"id": r["id"], "type": r["type"], "reasons": reasons})
    return out


def markdown(result: Dict[str, Any]) -> str:
    s = result["summary"]
    lines = [f"# Lecture assistant evaluation, {result['run']}", "",
             f"Questions: `{result['questions_file']}` (version {result['questions_version']}), "
             f"{s['questions']} questions, {s['evaluated']} evaluated, {s['unavailable']} unavailable.", "",
             "## Summary", "",
             "| Measure | Value |", "|---|---|",
             f"| Decision accuracy (answer or refuse) | {_pct(s['decision_accuracy'])} |",
             f"| Refusal precision | {_pct(s['refusal_precision'])} |",
             f"| Refusal recall | {_pct(s['refusal_recall'])} |",
             f"| Hit@1 | {_pct(s['hit_at_1'])} |", f"| Hit@5 | {_pct(s['hit_at_5'])} |",
             f"| Complete answers | {_pct(s['complete_answers'])} |",
             f"| Correct sources (of the answered) | {_pct(s['correct_sources'])} |",
             f"| needs_review | {s['needs_review']} |", f"| Mean time | {s['mean_seconds']} s |",
             f"| Unavailable | {s['unavailable']} |", f"| Chunks from a course not allowed | {s['leaks']} |", "",
             "## By question type", "",
             "| Type | n | Decision | Refusal P / R | Hit@1 | Hit@5 | Complete | Sources | Mean time | Unavailable |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for kind, t in result["by_type"].items():
        lines.append(f"| {kind} | {t['questions']} | {_pct(t['decision_accuracy'])} | {_pct(t['refusal_precision'])} / "
                     f"{_pct(t['refusal_recall'])} | {_pct(t['hit_at_1'])} | {_pct(t['hit_at_5'])} | "
                     f"{_pct(t['complete_answers'])} | {_pct(t['correct_sources'])} | {t['mean_seconds']} s | {t['unavailable']} |")
    lines += ["", "## Questions", "",
              "| ID | Type | Expected | Got | Rank | Complete | Cited OK | Time | Answer |", "|---|---|---|---|---|---|---|---|---|"]
    yes = lambda v: "-" if v is None else ("yes" if v else "no")  # noqa: E731
    for r in result["rows"]:
        text = " ".join((r.get("answer") or "").split())
        text = (text[:140] + "…") if len(text) > 140 else text
        lines.append(f"| {r['id']} | {r['type']} | {r['expected_status']} | {r['status']} | {r.get('rank') or '-'} | "
                     f"{yes(r.get('complete'))} | {yes(r.get('source_ok'))} | {r.get('seconds')} s | {text.replace('|', '/')} |")
    fails = failures(result["rows"])
    lines += ["", "## Failures", ""]
    lines += [f"- **{f['id']}** ({f['type']}): " + "; ".join(f["reasons"]) for f in fails] or ["None."]
    return "\n".join(lines) + "\n"


def save(result: Dict[str, Any], folder, name: Optional[str] = None) -> Dict[str, str]:
    """eval-<time>.json/.md, or <name>.json/.md (an existing file is never overwritten)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = name or "eval-" + result["run"].replace(":", "").replace("-", "")
    json_path, md_path = folder / f"{stem}.json", folder / f"{stem}.md"
    if json_path.exists() or md_path.exists():
        raise FileExistsError(f"{json_path} already exists: results are never overwritten")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(markdown(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
