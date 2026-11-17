"""Deterministic Arabic-script -> English technical-term correction using an approved glossary.

Pure Python, offline, no model calls. raw_text is never modified; text is raw_text with the
Arabic core of matched words replaced, so everything outside a correction (whitespace,
punctuation, other words) is byte-identical. Corrections never cross segment boundaries.

Rules (see README "Technical-term correction"):
  word  (alias >= 6 letters)   similarity >= 0.92 (hamza-alif swap costs 0.5, all else 1)
  word  (alias 4-5 letters)    exact
  phrase                       exact on every word
  short / acronym_*            exact AND two independent pieces of evidence:
                               E1 term is in the current slide's terms, and
                               E2 an independently accepted word/phrase term within +-3 words.
Ties or near-ties between terms (margin 0.05) leave the text unchanged.
"""
import re
import unicodedata
from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Tuple

from .glossary import FUZZY_MIN, Glossary, Term, comparison_key, hamza_fold
from .transcript import Segment

MIN_FUZZY_SIM = 0.92
AMBIGUITY_MARGIN = 0.05
EVIDENCE_WINDOW = 3
MIN_STEM = 3
# Longest first; whole word is always tried before any prefix.
PREFIXES = ("وال", "بال", "ال", "لل", "ل", "و", "ب")
INDEPENDENT = {"word", "phrase"}

_ARABIC_LETTERS = "ء-يً-ْٰـ"
_TOKEN = re.compile(r"\S+")
_CORE = re.compile(rf"[{_ARABIC_LETTERS}]+")


def _split_token(token: str):
    """(lead, core, trail) or None. Only Unicode punctuation/symbols (P*, S*) may surround the
    core, and the core must be basic Arabic letters, diacritics and tatweel only. Any other
    character (Persian/extended Arabic letters, stray combining marks, presentation forms,
    Latin, digits, format characters) makes the whole token ineligible: it is never split."""
    i, j = 0, len(token)
    while i < j and unicodedata.category(token[i])[0] in "PS":
        i += 1
    while j > i and unicodedata.category(token[j - 1])[0] in "PS":
        j -= 1
    core = token[i:j]
    if core and _CORE.fullmatch(core):
        return token[:i], core, token[j:]
    return None
_HAMZA_ALIF = set("اأإآ")
# Arabic letters that do not connect to a following letter.
_NON_JOINING = set("اأإآدذرزوؤةىء")


def format_replacement(prefix: str, term: str) -> str:
    """Display form written into `text`. Matching never depends on this.

    Joining prefix -> prefix + tatweel + space + term  (الـ API, لـ run experiment)
    Non-joining    -> prefix + space + term            (و API)
    No bidi control characters are inserted; RTL rendering is left to the frontend,
    which can use the stored `prefix` and `term` fields.
    """
    if not prefix:
        return term
    joiner = "" if prefix[-1] in _NON_JOINING else "ـ"
    return f"{prefix}{joiner} {term}"


def similarity(a: str, b: str) -> float:
    """1 - weighted Levenshtein / max length. Hamza-alif substitutions cost 0.5."""
    if a == b:
        return 1.0
    n, m = len(a), len(b)
    if not n or not m:
        return 0.0
    prev = [float(j) for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [float(i)] + [0.0] * m
        for j in range(1, m + 1):
            ca, cb = a[i - 1], b[j - 1]
            sub = 0.0 if ca == cb else (0.5 if ca in _HAMZA_ALIF and cb in _HAMZA_ALIF else 1.0)
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + sub)
        prev = cur
    return 1.0 - prev[m] / max(n, m)


def bounded_similarity(a: str, b: str, min_sim: float) -> Optional[float]:
    """similarity(a, b) if it is >= min_sim, else None. Same result as similarity(), but only
    computes the diagonal band reachable within the cost budget and stops early."""
    n, m = len(a), len(b)
    budget = (1.0 - min_sim) * max(n, m) + 1e-9
    if abs(n - m) > budget:
        return None
    if a == b:
        return 1.0
    k = int(budget)               # each insertion/deletion costs 1
    inf = float("inf")
    prev = [float(j) if j <= k else inf for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [inf] * (m + 1)
        if i <= k:
            cur[0] = float(i)
        for j in range(max(1, i - k), min(m, i + k) + 1):
            ca, cb = a[i - 1], b[j - 1]
            sub = 0.0 if ca == cb else (0.5 if ca in _HAMZA_ALIF and cb in _HAMZA_ALIF else 1.0)
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + sub)
        if min(cur) > budget:
            return None
        prev = cur
    cost = prev[m]
    return 1.0 - cost / max(n, m) if cost <= budget else None


class _Tok:
    __slots__ = ("start", "end", "lead", "core", "trail", "key")

    def __init__(self, m: re.Match):
        self.start, self.end = m.start(), m.end()
        p = _split_token(m.group())
        if p:
            self.lead, self.core, self.trail = p
            self.key = comparison_key(self.core)
        else:
            self.lead = self.core = self.trail = ""
            self.key = ""

    @property
    def core_start(self) -> int:
        return self.start + len(self.lead)

    @property
    def core_end(self) -> int:
        return self.end - len(self.trail)


def _splits(core: str) -> List[Tuple[str, str]]:
    """(prefix, stem) options: whole word first, then each listed prefix, longest first."""
    out = [("", core)]
    for p in PREFIXES:
        stem = core[len(p):]
        if core.startswith(p) and len(comparison_key(stem)) >= MIN_STEM:
            out.append((p, stem))
    return out


def _reachable_lengths(n: int):
    """Alias lengths that could still reach MIN_FUZZY_SIM (each length change costs 1)."""
    for length in range(max(FUZZY_MIN, int(n * MIN_FUZZY_SIM)), int(n / MIN_FUZZY_SIM) + 2):
        if abs(length - n) <= (1 - MIN_FUZZY_SIM) * max(length, n):
            yield length


def _fuzzy_pool(g: Glossary, n: int):
    for length in _reachable_lengths(n):
        yield from g.fuzzy_by_len.get(length, ())


def _fuzzy_candidates(g: Glossary, key: str):
    """Aliases worth scoring. When the cost budget is below 1 (max length <= 12 at 0.92),
    only hamza-alif swaps fit, so candidates are exactly those with the same folded key."""
    n = len(key)
    for length in _reachable_lengths(n):
        if (1 - MIN_FUZZY_SIM) * max(length, n) < 1:
            if length == n:
                yield from g.fuzzy_folded.get(hamza_fold(key), ())
        else:
            yield from g.fuzzy_by_len.get(length, ())


def _single_candidates(g: Glossary, tok: _Tok) -> List[Tuple[float, Term, str, str]]:
    """All (score, term, prefix, rule) matches for one word, over every prefix split."""
    found = []
    for prefix, stem in _splits(tok.core):
        key = comparison_key(stem)
        for term in g.single.get(key, []):
            rule = {"word": "word_exact", "short": "short_exact"}.get(term.kind, "acronym_exact")
            found.append((1.0, term, prefix, rule))
        if len(key) >= FUZZY_MIN:
            for akey, term in _fuzzy_candidates(g, key):
                if akey != key:
                    s = bounded_similarity(key, akey, MIN_FUZZY_SIM)
                    if s is not None:
                        found.append((round(s, 4), term, prefix, "word_fuzzy"))
    return found


def _multi_candidates(g: Glossary, toks: List[_Tok], i: int, n: int):
    """Exact multi-word match of toks[i:i+n]; prefix allowed on the first word only."""
    span = toks[i:i + n]
    if len(span) < n or any(not t.key for t in span):
        return []
    # punctuation may only appear before the first word and after the last word
    if span[0].trail or span[-1].lead or any(t.lead or t.trail for t in span[1:-1]):
        return []
    rest = tuple(t.key for t in span[1:])
    found = []
    for prefix, stem in _splits(span[0].core):
        keys = (comparison_key(stem),) + rest
        for term in g.multi.get(keys, []):
            rule = "phrase_exact" if term.kind == "phrase" else "acronym_exact"
            found.append((1.0, term, prefix, rule))
    return found


def _resolve(found):
    """Pick one candidate, or None when ambiguous / keep_arabic / nothing found."""
    if not found:
        return None
    best: Dict[str, tuple] = {}
    for c in found:  # per term: highest score, then whole word over prefixed split
        cur = best.get(c[1].term)
        if cur is None or (c[0], -len(c[2])) > (cur[0], -len(cur[2])):
            best[c[1].term] = c
    ranked = sorted(best.values(), key=lambda c: (-c[0], c[1].term))
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < AMBIGUITY_MARGIN:
        return None
    top = ranked[0]
    return None if top[1].keep_arabic else top


def _find(g: Glossary, toks: List[_Tok]):
    """Greedy left-to-right, longest multi-word match first, non-overlapping."""
    matches, i = [], 0
    while i < len(toks):
        if not toks[i].key or toks[i].key in g.never_correct:
            i += 1
            continue
        hit = None
        for n in range(g.max_phrase_words, 1, -1):
            if any(t.key in g.never_correct for t in toks[i:i + n]):
                continue
            found = _multi_candidates(g, toks, i, n)
            if found:
                hit = (_resolve(found), n)
                break
        if hit is None:
            hit = (_resolve(_single_candidates(g, toks[i])), 1)
        cand, n = hit
        if cand is not None:
            matches.append((i, i + n, cand))
            i += n
        else:
            i += 1
    return matches


def correct_text(raw: str, glossary: Glossary,
                 slide_terms: Optional[Iterable[str]] = None) -> Tuple[str, List[dict]]:
    """Return (text, corrections) for one segment's raw text. raw is never modified."""
    toks = [_Tok(m) for m in _TOKEN.finditer(raw)]
    matches = _find(glossary, toks)
    slide = {t.casefold() for t in (slide_terms or ())}
    # Evidence comes only from these original independent matches; accepted short-term or
    # acronym corrections never count as evidence for each other (no chaining).
    independent = [m for m in matches if m[2][1].kind in INDEPENDENT]
    accepted = list(independent)
    for m in matches:
        term = m[2][1]
        if term.kind in INDEPENDENT:
            continue
        evidence = []
        if term.term.casefold() in slide:
            evidence.append("slide_term")
        near = sorted({a[2][1].term for a in independent
                       if a[0] - EVIDENCE_WINDOW <= m[1] - 1 and m[0] <= a[1] - 1 + EVIDENCE_WINDOW})
        if near:
            evidence.append("adjacent_term:" + ",".join(near))
        if len(evidence) == 2:
            accepted.append(m + (evidence,))
    accepted.sort(key=lambda m: m[0])

    corrections, parts, pos = [], [], 0
    for m in accepted:
        a, b, (score, term, prefix, rule) = m[0], m[1], m[2]
        cs, ce = toks[a].core_start, toks[b - 1].core_end
        replacement = format_replacement(prefix, term.term)
        parts += [raw[pos:cs], replacement]
        pos = ce
        corrections.append({
            "token_start": a, "token_end": b, "char_start": cs, "char_end": ce,
            "original": raw[cs:ce], "prefix": prefix, "term": term.term, "kind": term.kind,
            "replacement": replacement, "confidence": score, "rule": rule,
            "evidence": m[3] if len(m) > 3 else []})
    parts.append(raw[pos:])
    return "".join(parts), corrections


def correct_segments(segments: List[Segment], glossary: Glossary,
                     slide_terms: Optional[Dict[int, Iterable[str]]] = None) -> List[Segment]:
    """Return new segments with raw_text/corrections set. Timing, order and slide are unchanged.

    Re-correcting a segment always starts from its existing raw_text.
    """
    out = []
    for s in segments:
        raw = s.raw_text if s.raw_text is not None else s.text
        terms = (slide_terms or {}).get(s.slide) if s.slide is not None else None
        text, corr = correct_text(raw, glossary, terms)
        out.append(replace(s, text=text, raw_text=raw, corrections=corr))
    return out
