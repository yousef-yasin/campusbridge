"""Evaluate glossary term correction against a human-corrected reference transcript.

Usage (from ai/speech-to-text):
  python eval/score_terms.py REFERENCE HYPOTHESIS.json [--glossary approved.json]

REFERENCE   human-corrected transcript (.txt, or .json with "full_text"), written with the
            team's term convention (English terms in Latin script).
HYPOTHESIS  transcript JSON saved with glossary correction enabled (has raw_text/corrections).
--glossary  re-apply correction from raw_text with this frozen glossary and time it.

Only use recordings that were NOT used to create glossary aliases or tune thresholds.

Metrics
  precision           correct corrections / all corrections (a correction is correct when all
                      of its words align to the same words in the reference)
  recall (words)      reference English words gained by correction / reference English words
                      that the raw output did not already have
  false corrections   incorrect corrections per 1,000 reference Arabic words
  WER before/after    raw_text vs text, overall / Arabic / English (conservative normalization:
                      diacritics, tatweel and punctuation removed, Latin lowercased; no letter
                      mapping between Arabic letters)
"""
import argparse
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stt.transcript import Transcript  # noqa: E402

_MARKS = re.compile(r"[ً-ْٰـ]")
_PUNCT = re.compile(r"[،؛؟]|[^\w\s.]|(?<!\w)\.|\.(?!\w)")
_LATIN = re.compile(r"[a-z]")


def words(text: str):
    t = _MARKS.sub("", text).replace("-", " ").lower()
    return _PUNCT.sub(" ", t).split()


def lang(w: str) -> str:
    return "en" if _LATIN.search(w) else "ar"


def align(ref, hyp):
    n, m = len(ref), len(hyp)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j] + 1, D[i][j - 1] + 1, D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    ops, i, j = [], n, m
    while i or j:
        if i and j and D[i][j] == D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("OK" if ref[i - 1] == hyp[j - 1] else "SUB", ref[i - 1], hyp[j - 1])); i -= 1; j -= 1
        elif i and D[i][j] == D[i - 1][j] + 1:
            ops.append(("DEL", ref[i - 1], "")); i -= 1
        else:
            ops.append(("INS", "", hyp[j - 1])); j -= 1
    return list(reversed(ops))


def wer(ref_text: str, hyp_text: str) -> dict:
    ref, hyp = words(ref_text), words(hyp_text)
    ops = align(ref, hyp)
    errs = {"ar": 0, "en": 0}
    for k, o in enumerate(ops):
        if o[0] in ("SUB", "DEL"):
            errs[lang(o[1])] += 1
        elif o[0] == "INS":          # attribute to an adjacent error's language, else the word's
            near = [ops[x] for x in (k - 1, k + 1) if 0 <= x < len(ops) and ops[x][0] in ("SUB", "DEL")]
            errs[lang(near[0][1]) if near else lang(o[2])] += 1
    n = {L: sum(lang(w) == L for w in ref) for L in errs}
    pct = lambda e, d: round(100.0 * e / d, 2) if d else None
    return {"overall": pct(sum(errs.values()), len(ref)), "ar": pct(errs["ar"], n["ar"]),
            "en": pct(errs["en"], n["en"]), "ref_words": len(ref), "ref_ar_words": n["ar"]}


def _hyp_latin(t: Transcript):
    """Latin words of the corrected text in order, tagged with the correction that produced them."""
    out, cid = [], 0
    for s in t.segments:
        raw = s.raw_text if s.raw_text is not None else s.text
        pos = 0
        for c in sorted(s.corrections or [], key=lambda c: c["char_start"]):
            out += [(w, None) for w in words(raw[pos:c["char_start"]]) if lang(w) == "en"]
            out += [(w, cid) for w in words(c["term"])]
            cid += 1
            pos = c["char_end"]
        out += [(w, None) for w in words(raw[pos:]) if lang(w) == "en"]
    return out, cid


def score(ref_text: str, t: Transcript) -> dict:
    if any(s.raw_text is None for s in t.segments):
        raise SystemExit("hypothesis must be saved with glossary correction enabled (raw_text missing)")
    ref_en = [w for w in words(ref_text) if lang(w) == "en"]
    hyp_en, n_corr = _hyp_latin(t)
    matched = set()
    for a, b, size in SequenceMatcher(None, ref_en, [w for w, _ in hyp_en], autojunk=False).get_matching_blocks():
        matched.update(b + k for k in range(size))
    per_corr = {}
    for idx, (_, cid) in enumerate(hyp_en):
        if cid is not None:
            per_corr.setdefault(cid, []).append(idx in matched)
    tp = sum(all(v) for v in per_corr.values())
    fp = n_corr - tp
    raw_en = [w for w in words(t.raw_full_text) if lang(w) == "en"]
    raw_hits = sum(b.size for b in SequenceMatcher(None, ref_en, raw_en, autojunk=False).get_matching_blocks())
    gained = sum(1 for idx, (_, cid) in enumerate(hyp_en) if cid is not None and idx in matched)
    before, after = wer(ref_text, t.raw_full_text), wer(ref_text, t.full_text)
    missing = max(len(ref_en) - raw_hits, 0)
    return {
        "corrections": n_corr, "correct": tp, "false": fp,
        "precision": round(tp / n_corr, 4) if n_corr else None,
        "recall_words": round(gained / missing, 4) if missing else None,
        "false_per_1000_ar_words": round(1000.0 * fp / before["ref_ar_words"], 2) if before["ref_ar_words"] else None,
        "wer_before": before, "wer_after": after,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reference")
    ap.add_argument("hypothesis")
    ap.add_argument("--glossary", help="re-apply correction from raw_text with this glossary and time it")
    args = ap.parse_args(argv)
    ref_path = Path(args.reference)
    ref_text = ref_path.read_text(encoding="utf-8")
    if ref_path.suffix == ".json":
        ref_text = json.loads(ref_text)["full_text"]
    t = Transcript.load(args.hypothesis)
    result = {}
    if args.glossary:
        from stt.glossary import load_glossary
        from stt.termfix import correct_segments
        g = load_glossary(args.glossary)
        if t.glossary and t.glossary.get("sha256") != g.sha256:
            print("warning: glossary differs from the one recorded in the transcript", file=sys.stderr)
        t0 = time.perf_counter()
        t.segments = correct_segments(t.segments, g)
        ms = (time.perf_counter() - t0) * 1000
        result["latency_ms"] = {"total": round(ms, 2), "per_segment": round(ms / max(len(t.segments), 1), 3)}
        t.glossary = g.info
    result.update(score(ref_text, t))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
