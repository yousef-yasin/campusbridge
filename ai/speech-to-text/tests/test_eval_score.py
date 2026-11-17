import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from glossary_data import demo  # noqa: E402
from score_terms import main, score, wer, words  # noqa: E402
from stt.glossary import build  # noqa: E402
from stt.termfix import correct_segments  # noqa: E402
from stt.transcript import Segment, Transcript  # noqa: E402

G = build(demo())


def _hyp(*raws):
    return Transcript(correct_segments([Segment(i, i + 1, r) for i, r in enumerate(raws)], G),
                      glossary=G.info)


def test_words_normalization_is_conservative():
    assert words("الـ Requirements، و مَكتبة.") == ["ال", "requirements", "و", "مكتبة"]
    assert words("ASP.NET Speech-to-Text") == ["asp.net", "speech", "to", "text"]
    assert words("مكتبة") != words("مكتبه")


def test_score_counts_correct_and_false_corrections():
    ref = "لكي تابت الـ algorithm حللنا دفعت كاش"
    # "كاش" is corrected to cache with full evidence, but the reference says it is Arabic (cash)
    t = Transcript(correct_segments([Segment(0, 1, "لكي تابت الالجوريثم حللنا", slide=1),
                                     Segment(1, 2, "الداتابيس دفعت كاش", slide=1)],
                                    G, {1: ["cache"]}), glossary=G.info)
    r = score(ref + "", t)
    assert (r["corrections"], r["correct"], r["false"]) == (3, 1, 2)       # algorithm ok; database, cache wrong
    assert r["precision"] == round(1 / 3, 4)
    assert r["recall_words"] == 1.0
    assert r["wer_before"]["ref_ar_words"] == 6                         # لكي تابت ال حللنا دفعت كاش
    assert r["false_per_1000_ar_words"] == round(1000 * 2 / 6, 2)


def test_wer_before_after_and_languages():
    ref = "اللي هي الـ implementation"
    t = _hyp("اللي هي الابليمنتيشن")
    r = score(ref, t)
    assert r["wer_before"]["overall"] == 50.0 and r["wer_after"]["overall"] == 0.0
    assert r["wer_after"]["ar"] == 0.0 and r["wer_after"]["en"] == 0.0
    assert wer("a b", "a b")["overall"] == 0.0


def test_cli_with_glossary_reapplication(tmp_path, capsys):
    hyp = _hyp("اللي هي الابليمنتيشن").save(tmp_path / "h.txt").with_suffix(".json")
    ref = tmp_path / "ref.txt"
    ref.write_text("اللي هي الـ implementation", encoding="utf-8")
    g = tmp_path / "g.json"
    g.write_text(json.dumps(demo(), ensure_ascii=False), encoding="utf-8")
    main([str(ref), str(hyp), "--glossary", str(g)])
    out = json.loads(capsys.readouterr().out)
    assert out["precision"] == 1.0 and "latency_ms" in out
