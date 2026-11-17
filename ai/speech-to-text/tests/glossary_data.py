"""Synthetic demo glossary for unit tests (hand-written; not derived from evaluation recordings)."""
import copy

DEMO = {
    "schema": 1, "course": "DEMO101", "version": 1,
    "approved_by": "test-instructor", "approved_at": "2026-11-16",
    "terms": [
        {"term": "algorithm", "kind": "word", "aliases": [
            {"ar": "الجوريثم", "status": "approved", "source": "rule"},
            {"ar": "الغوريتم", "status": "approved", "source": "rule"},
            {"ar": "الجورزم", "status": "proposed", "source": "rule"}]},
        {"term": "implementation", "kind": "word", "aliases": [
            {"ar": "ابليمنتيشن", "status": "approved", "source": "rule"},
            {"ar": "امبليمنتيشن", "status": "approved", "source": "rule"}]},
        {"term": "database", "kind": "word", "aliases": [{"ar": "داتابيس", "status": "approved"}]},
        {"term": "Python", "kind": "word", "aliases": [{"ar": "بايثون", "status": "approved"}]},
        {"term": "time", "kind": "word", "aliases": [{"ar": "تايم", "status": "approved"}]},
        {"term": "space", "kind": "word", "aliases": [{"ar": "سبيس", "status": "approved"}]},
        {"term": "run experiment", "kind": "phrase", "aliases": [
            {"ar": "ران اكسبريمنت", "status": "approved"}]},
        {"term": "run", "kind": "short", "aliases": [
            {"ar": "ران", "status": "approved"}, {"ar": "رن", "status": "approved"}]},
        {"term": "cache", "kind": "short", "aliases": [{"ar": "كاش", "status": "approved"}]},
        {"term": "loop", "kind": "short", "aliases": [{"ar": "لوب", "status": "approved"}]},
        {"term": "API", "kind": "acronym_letters", "aliases": [
            {"ar": "اي بي اي", "status": "approved", "source": "letters"}]},
        {"term": "AI", "kind": "acronym_letters", "aliases": [
            {"ar": "ايه اي", "status": "approved", "source": "letters"},
            {"ar": "اي اي", "status": "proposed", "source": "letters"}]},
        {"term": "SQL", "kind": "acronym_word", "aliases": [{"ar": "سيكول", "status": "approved"}]},
        {"term": "model", "kind": "word", "keep_arabic": True, "aliases": [
            {"ar": "موديل", "status": "approved"}]},
    ],
    "never_correct": ["بدنا", "بعدما"],
}


def demo(**changes):
    from stt.glossary import seal
    d = copy.deepcopy(DEMO)
    d.update(changes)
    return seal(d)
