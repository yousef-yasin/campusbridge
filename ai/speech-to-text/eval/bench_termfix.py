"""Latency/memory benchmark for the term-correction layer (synthetic data, deterministic).

Run from ai/speech-to-text:  python eval/bench_termfix.py [--terms 500] [--segments 2000]
"""
import argparse
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stt.glossary import build, seal  # noqa: E402
from stt.termfix import correct_text  # noqa: E402

LETTERS = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"
COMMON = ["يعني", "اليوم", "رح", "نحكي", "عن", "المشروع", "وبعدها", "عملنا", "لازم", "البرنامج",
          "حللنا", "طلعنا", "كل", "هذا", "على", "ورق", "اعتمدنا", "حولنا", "للبرمجة", "اللي", "هي"]


def synthetic_glossary(n_terms: int, rng: random.Random) -> dict:
    seen, terms = set(), []

    def word(lo, hi):
        while True:
            w = "".join(rng.choice(LETTERS) for _ in range(rng.randint(lo, hi)))
            if w not in seen:
                seen.add(w)
                return w

    for i in range(n_terms):
        r = i % 50
        if r < 40:
            kind, aliases = "word", [word(4, 12) for _ in range(2)]
        elif r < 45:
            kind, aliases = "phrase", [f"{word(3, 7)} {word(4, 9)}"]
        elif r < 48:
            kind, aliases = "short", [word(2, 3)]
        else:
            kind, aliases = "acronym_letters", [f"{word(2, 3)} {word(2, 3)} {word(2, 3)}"]
        term = f"term{i}" if kind != "phrase" else f"term{i} part"
        terms.append({"term": term, "kind": kind,
                      "aliases": [{"ar": a, "status": "approved"} for a in aliases]})
    return seal({"schema": 1, "course": "BENCH", "version": 1, "terms": terms, "never_correct": []})


def segments(data: dict, n: int, words: int, rng: random.Random):
    aliases = [a["ar"] for t in data["terms"] for a in t["aliases"]]
    out = []
    for _ in range(n):
        toks = []
        while len(toks) < words:
            r = rng.random()
            if r < 0.05:
                toks.append(rng.choice(["ال", "و", "ل", ""]) + rng.choice(aliases))
            elif r < 0.7:
                toks.append("".join(rng.choice(LETTERS) for _ in range(rng.randint(6, 11))))
            else:
                toks.append(rng.choice(COMMON))
        out.append(" ".join(toks[:words]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", type=int, default=500)
    ap.add_argument("--segments", type=int, default=2000)
    args = ap.parse_args(argv)
    rng = random.Random(0)
    data = synthetic_glossary(args.terms, rng)

    tracemalloc.start()
    t0 = time.perf_counter()
    g = build(data)
    build_ms = (time.perf_counter() - t0) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    n_alias = sum(len(t["aliases"]) for t in data["terms"])
    print(f"glossary: {args.terms} terms, {n_alias} aliases, build {build_ms:.1f} ms, "
          f"peak alloc {peak / 2**20:.2f} MiB")

    for words, label in ((10, "live 5 s chunk (~10 words)"), (40, "file segment (~40 words)")):
        segs = segments(data, args.segments, words, rng)
        times, n_corr = [], 0
        for s in segs:
            t0 = time.perf_counter()
            _, corr = correct_text(s, g, ["term0"])
            times.append((time.perf_counter() - t0) * 1000)
            n_corr += len(corr)
        times.sort()
        p = lambda q: times[min(len(times) - 1, int(q * len(times)))]
        total_words = words * len(segs)
        per_hour_s = statistics.mean(times) / words * 7200 / 1000   # ~120 words/minute speech
        print(f"{label}: p50 {p(0.5):.2f} ms, p95 {p(0.95):.2f} ms, max {times[-1]:.2f} ms, "
              f"{total_words / (sum(times) / 1000):,.0f} words/s, ~{per_hour_s:.2f} s per hour "
              f"of speech, corrections={n_corr}")


if __name__ == "__main__":
    main()
