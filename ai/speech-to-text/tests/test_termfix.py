import re

import pytest

from glossary_data import DEMO, demo
from stt.glossary import build, seal
from stt.termfix import correct_segments, correct_text, format_replacement, similarity
from stt.transcript import Segment

G = build(demo())
BIDI = re.compile("[‎‏‪-‮⁦-⁩]")


def fix(raw, slide=None, g=G):
    return correct_text(raw, g, slide)


def check_invariants(raw, text, corrections):
    """Everything outside corrections is byte-identical; each original is the exact raw span."""
    rebuilt, pos = [], 0
    for c in corrections:
        assert raw[c["char_start"]:c["char_end"]] == c["original"]
        assert c["original"] == c["prefix"] + c["original"][len(c["prefix"]):]
        rebuilt += [raw[pos:c["char_start"]], c["replacement"]]
        pos = c["char_end"]
    rebuilt.append(raw[pos:])
    assert "".join(rebuilt) == text
    for word in text.split():
        assert not (re.search("[ء-ي]", word) and re.search("[A-Za-z]", word)), word


# --- word terms -------------------------------------------------------------------------

def test_word_exact_with_prefix_keeps_prefix_separate():
    raw = "لكي تابت الالجوريثم حللنا"
    text, corr = fix(raw)
    assert text == "لكي تابت الـ algorithm حللنا"
    c, = corr
    assert (c["original"], c["prefix"], c["term"], c["rule"], c["confidence"]) == \
        ("الالجوريثم", "ال", "algorithm", "word_exact", 1.0)
    assert (c["token_start"], c["token_end"]) == (2, 3)
    check_invariants(raw, text, corr)


def test_punctuation_and_whitespace_preserved():
    raw = "  اللي هي الابليمنتيشن.\t\tو  سبيس،  "
    text, corr = fix(raw)
    assert text == "  اللي هي الـ implementation.\t\tو  space،  "
    check_invariants(raw, text, corr)


def test_fuzzy_allows_hamza_variant_only_on_long_aliases():
    text, corr = fix("إبليمنتيشن")
    assert text == "implementation" and corr[0]["rule"] == "word_fuzzy"
    assert corr[0]["confidence"] == pytest.approx(0.95)
    assert fix("ابليمنتيشم")[1] == []           # one real letter change on 10 letters: 0.90 < 0.92
    assert fix("سبيز")[1] == []                 # 4-5 letter aliases: exact only
    assert fix("تايمم")[1] == []


def test_keep_arabic_term_is_never_replaced():
    assert fix("موديل الشركة") == ("موديل الشركة", [])


# --- phrases ------------------------------------------------------------------------------

def test_phrase_exact_with_prefix():
    raw = "بدنا نعمل لران اكسبريمنت"
    text, corr = fix(raw)
    assert text == "بدنا نعمل لـ run experiment"
    assert corr[0]["rule"] == "phrase_exact" and corr[0]["prefix"] == "ل"
    assert (corr[0]["token_start"], corr[0]["token_end"]) == (2, 4)
    check_invariants(raw, text, corr)


def test_phrase_broken_by_punctuation_is_not_matched():
    assert fix("ران، اكسبريمنت")[1] == []


# --- short terms and acronyms: two pieces of evidence -------------------------------------

def test_short_term_needs_slide_and_adjacent_term():
    raw = "الداتابيس ران بسرعة"
    assert fix(raw)[0] == "الـ database ران بسرعة"                     # no slide context
    assert fix(raw, slide=["run"])[0] == "الـ database ran بسرعة".replace("ran", "run")
    text, corr = fix(raw, slide=["run"])
    c = corr[1]
    assert c["rule"] == "short_exact"
    assert c["evidence"] == ["slide_term", "adjacent_term:database"]
    assert fix("خلينا ران البرنامج", slide=["run"])[1] == []             # slide alone: not enough


def test_short_term_adjacency_window():
    far = "الداتابيس واحد اثنين ثلاث اربع ران"                                # 5 words away
    assert all(c["term"] != "run" for c in fix(far, slide=["run"])[1])
    near = "الداتابيس واحد اثنين ران"                                        # 3 words away
    assert any(c["term"] == "run" for c in fix(near, slide=["run"])[1])


def test_acronym_letters_rules():
    raw = "نستدعي اي بي اي من الداتابيس"
    assert fix(raw)[0] == "نستدعي اي بي اي من الـ database"               # no slide: unchanged
    text, corr = fix(raw, slide=["API"])
    assert text == "نستدعي API من الـ database"
    assert corr[0]["rule"] == "acronym_exact" and corr[0]["kind"] == "acronym_letters"
    check_invariants(raw, text, corr)
    # proposed pronunciation is never used, even with evidence
    assert all(c["term"] != "AI" for c in fix("اي اي مع الداتابيس", slide=["AI"])[1])
    # a single letter-name word never matches an acronym
    assert all(c["term"] != "API" for c in fix("اي الداتابيس", slide=["API"])[1])


def test_acronym_word_needs_evidence():
    assert fix("سيكول")[1] == []
    assert fix("سيكول", slide=["SQL"])[1] == []
    assert fix("سيكول والداتابيس", slide=["SQL"])[0] == "SQL والـ database"


# --- ambiguity, determinism, segments ------------------------------------------------------

def test_ambiguous_prefix_split_leaves_text_unchanged():
    data = demo()
    data["terms"].append({"term": "gorithm", "kind": "word", "aliases": [
        {"ar": "جوريثم", "status": "approved"}]})
    g = build(seal(data))
    assert fix("الجوريثم", g=g) == ("الجوريثم", [])                         # algorithm vs ال+gorithm


def test_never_correct_word_is_skipped():
    data = demo()
    data["terms"].append({"term": "budna", "kind": "word", "aliases": [
        {"ar": "بدنا", "status": "approved"}]})
    assert fix("بدنا", g=build(seal(data))) == ("بدنا", [])


def test_deterministic_regardless_of_glossary_order():
    data = demo()
    data["terms"] = list(reversed(data["terms"]))
    g2 = build(seal(data))
    raw = "الالجوريثم و اي بي اي مع الداتابيس لران اكسبريمنت"
    assert fix(raw, ["API"]) == fix(raw, ["API"], g=g2)


def test_correct_segments_preserves_timing_order_slide_and_raw():
    segs = [Segment(0.0, 2.5, "صباح الخير", slide=1),
            Segment(2.5, 5.0, "الالجوريثم  هون", slide=1),
            Segment(5.0, 9.0, "نستدعي اي بي اي من الداتابيس", slide=2)]
    out = correct_segments(segs, G, slide_terms={2: ["API"]})
    assert [(s.start, s.end, s.slide) for s in out] == [(s.start, s.end, s.slide) for s in segs]
    assert [s.raw_text for s in out] == [s.text for s in segs]
    assert out[0].corrections == [] and out[0].text == "صباح الخير"
    assert out[1].text == "الـ algorithm  هون"
    assert out[2].text == "نستدعي API من الـ database"
    assert segs[1].raw_text is None and segs[1].text == "الالجوريثم  هون"     # inputs untouched
    again = correct_segments(out, G, slide_terms={2: ["API"]})               # re-correction from raw
    assert [(s.text, s.raw_text, s.corrections) for s in again] == \
           [(s.text, s.raw_text, s.corrections) for s in out]


# --- display formatting (separate from matching) -------------------------------------------

@pytest.mark.parametrize("prefix,term,expected", [
    ("", "API", "API"),
    ("ال", "API", "الـ API"),
    ("وال", "API", "والـ API"),
    ("بال", "API", "بالـ API"),
    ("لل", "server", "للـ server"),
    ("ل", "run experiment", "لـ run experiment"),
    ("ب", "Python", "بـ Python"),
    ("و", "API", "و API"),                       # و does not join: no tatweel
])
def test_format_replacement(prefix, term, expected):
    out = format_replacement(prefix, term)
    assert out == expected
    assert not BIDI.search(out)                  # no invisible direction marks stored
    assert out.split(" ", 1)[-1] == term if prefix else out == term


def test_fuzzy_length_pruning_never_drops_a_reachable_alias():
    from types import SimpleNamespace
    from stt.termfix import MIN_FUZZY_SIM, _fuzzy_pool
    g = SimpleNamespace(fuzzy_by_len={L: [(str(L), None)] for L in range(6, 40)})
    for n in range(6, 35):
        pooled = {int(k) for k, _ in _fuzzy_pool(g, n)}
        for L in range(6, 40):
            reachable = abs(L - n) <= (1 - MIN_FUZZY_SIM) * max(L, n)
            assert (L in pooled) == reachable, (n, L)


def test_bounded_similarity_matches_full_similarity():
    import random
    from stt.termfix import MIN_FUZZY_SIM, bounded_similarity
    rng = random.Random(1)
    letters = "اأإآبتسشلمنيو"
    for _ in range(4000):
        a = "".join(rng.choice(letters) for _ in range(rng.randint(6, 20)))
        b = list(a)
        for _ in range(rng.randint(0, 3)):           # small random edits
            op, pos = rng.randint(0, 2), rng.randrange(len(b) + 1)
            if op == 0 and pos < len(b):
                b[pos] = rng.choice(letters)
            elif op == 1:
                b.insert(pos, rng.choice(letters))
            elif pos < len(b):
                del b[pos]
        b = "".join(b)
        full = similarity(a, b)
        got = bounded_similarity(a, b, MIN_FUZZY_SIM)
        if full >= MIN_FUZZY_SIM:
            assert got == pytest.approx(full), (a, b)
        else:
            assert got is None, (a, b, full)


def test_fuzzy_index_equals_brute_force():
    """Indexed candidate search finds exactly what scoring every long alias would find."""
    import random
    from stt.glossary import seal as _seal
    from stt.termfix import MIN_FUZZY_SIM, _fuzzy_candidates, bounded_similarity
    rng = random.Random(2)
    letters = "اأإآبتسشلمنيوك"
    seen, terms = set(), []
    while len(terms) < 300:
        w = "".join(rng.choice(letters) for _ in range(rng.randint(6, 18)))
        if w not in seen:
            seen.add(w)
            terms.append({"term": f"t{len(terms)}", "kind": "word",
                          "aliases": [{"ar": w, "status": "approved"}]})
    g = build(_seal({"schema": 1, "course": "X", "version": 1, "terms": terms}))
    aliases = [k for k, _ in g.fuzzy]
    for _ in range(3000):
        b = list(rng.choice(aliases))
        for _ in range(rng.randint(0, 2)):
            pos = rng.randrange(len(b))
            r = rng.random()
            if r < 0.5:
                b[pos] = rng.choice("اأإآ")
            elif r < 0.75:
                b[pos] = rng.choice(letters)
            elif r < 0.9:
                b.insert(pos, rng.choice(letters))
            elif len(b) > 6:
                del b[pos]
        key = "".join(b)
        brute = {(a, t.term) for a, t in g.fuzzy if bounded_similarity(key, a, MIN_FUZZY_SIM)}
        fast = {(a, t.term) for a, t in _fuzzy_candidates(g, key)
                if bounded_similarity(key, a, MIN_FUZZY_SIM)}
        assert fast == brute, key


def test_similarity():
    assert similarity("ابليمنتيشن", "ابليمنتيشن") == 1.0
    assert similarity("إبليمنتيشن", "ابليمنتيشن") == pytest.approx(0.95)
    assert similarity("مكتبة", "مكتبه") == pytest.approx(0.8)            # ة vs ه is a full edit
