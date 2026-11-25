from types import SimpleNamespace

import numpy as np
import pytest

from stt import Segment, STTConfig, Transcriber, codeswitch
from stt.codeswitch import _gaps, refine

AUDIO = np.zeros(16000 * 20, dtype=np.float32)


class ScriptedModel:
    """detect_language / transcribe answers chosen by the clip's start time (seconds)."""

    def __init__(self, langs=None, texts=None, primary=(), logprob=-0.2):
        self.langs, self.texts, self.primary, self.logprob = langs or {}, texts or {}, primary, logprob
        self.offset = 0.0
        self.calls = []

    def _key(self, clip):
        keys = set(self.langs) | set(self.texts)
        return next((k for k in keys if abs(k - self.offset) < 0.01), None)

    def detect_language(self, clip):
        p = self.langs.get(self._key(clip), {"ar": 1.0})
        return max(p, key=p.get), max(p.values()), list(p.items())

    def transcribe(self, audio, language=None, **kw):
        self.calls.append(language)
        if audio is AUDIO or kw.get("vad_filter"):
            segs = self.primary
        else:
            segs = [(0, 1, self.texts.get(self._key(audio), ""))]
        return iter(SimpleNamespace(start=s, end=e, text=t, avg_logprob=self.logprob,
                                    no_speech_prob=0.0) for s, e, t in segs), None


@pytest.fixture
def track_offset(monkeypatch):
    """Make the scripted model know which clip it is looking at."""
    def wire(model):
        real = codeswitch._clip
        def clip(audio, start, end):
            model.offset = start
            return real(audio, start, end)
        monkeypatch.setattr(codeswitch, "_clip", clip)
    return wire


def test_repass_replaces_transliteration_keeps_timing_and_slide(track_offset, monkeypatch):
    monkeypatch.setattr(codeswitch, "_speech_regions", lambda a: [])
    m = ScriptedModel(langs={5.0: {"en": 0.98, "ar": 0.01}}, texts={5.0: " Entities"})
    track_offset(m)
    segs = [Segment(0.0, 3.0, "وحددنا"), Segment(5.0, 6.0, "انتو تيز", slide=2)]
    out = refine(m, AUDIO, segs, "ar")
    assert out[0].text == "وحددنا"
    assert (out[1].start, out[1].end, out[1].text, out[1].slide) == (5.0, 6.0, "Entities", 2)


def test_repass_ignores_low_confidence_and_long_segments(track_offset, monkeypatch):
    monkeypatch.setattr(codeswitch, "_speech_regions", lambda a: [])
    m = ScriptedModel(langs={1.0: {"en": 0.5, "ar": 0.1}, 3.0: {"en": 0.99}}, texts={1.0: "what", 3.0: "x"})
    track_offset(m)
    segs = [Segment(1.0, 1.6, "و"), Segment(3.0, 9.0, "جملة طويلة فيها Python")]
    out = refine(m, AUDIO, segs, "ar")
    assert [s.text for s in out] == ["و", "جملة طويلة فيها Python"]


def test_gap_recovery_adds_english_segment_in_order(track_offset, monkeypatch):
    monkeypatch.setattr(codeswitch, "_speech_regions", lambda a: [(0.0, 3.0), (7.8, 10.2)])
    m = ScriptedModel(langs={7.65: {"en": 0.99}}, texts={7.65: " Requirements Analysis"})
    track_offset(m)
    out = refine(m, AUDIO, [Segment(0.0, 3.0, "صباح الخير"), Segment(11.0, 14.0, "إلى مرحلة")], "ar")
    assert [s.text for s in out] == ["صباح الخير", "Requirements Analysis", "إلى مرحلة"]
    assert (out[1].start, out[1].end) == (7.8, 10.2)


def test_gap_recovery_drops_uncertain_or_low_confidence(track_offset, monkeypatch):
    monkeypatch.setattr(codeswitch, "_speech_regions", lambda a: [(4.0, 6.0)])
    m = ScriptedModel(langs={3.85: {"en": 0.6, "ar": 0.3}}, texts={3.85: "art"})
    track_offset(m)
    assert refine(m, AUDIO, [], "ar") == []
    m = ScriptedModel(langs={3.85: {"en": 0.95}}, texts={3.85: "lit"}, logprob=-2.0)
    track_offset(m)
    assert refine(m, AUDIO, [], "ar") == []


def test_gaps_only_uncovered_speech():
    segs = [Segment(1.0, 2.0, "a"), Segment(2.1, 4.0, "b")]
    assert _gaps([(0.0, 5.0)], segs) == [(0.0, 1.0), (4.0, 5.0)]   # 0.1 s gap ignored
    assert _gaps([(1.2, 1.8)], segs) == []


def test_transcriber_offset_applied_after_refine(monkeypatch):
    monkeypatch.setattr(codeswitch, "_speech_regions", lambda a: [])
    m = ScriptedModel(primary=[(0.0, 2.0, "مرحبا")])
    segs = Transcriber(STTConfig(code_switching=True), model=m).transcribe_chunk(AUDIO, offset=30.0)
    assert (segs[0].start, segs[0].end) == (30.0, 32.0)


@pytest.mark.parametrize("cfg", [STTConfig(), STTConfig(code_switching=True, language="en"),
                                 STTConfig(code_switching=True, language=None)])
def test_code_switching_skipped(cfg, monkeypatch):
    monkeypatch.setattr(codeswitch, "refine", lambda *a, **k: pytest.fail("refine called"))
    m = ScriptedModel(primary=[(0.0, 1.0, "x")])
    assert Transcriber(cfg, model=m).transcribe_chunk(AUDIO)[0].text == "x"


def test_code_switching_is_opt_in(monkeypatch):
    assert STTConfig().code_switching is False
    assert STTConfig.from_env().code_switching is False
    monkeypatch.setenv("STT_CODE_SWITCHING", "1")
    assert STTConfig.from_env().code_switching is True
    assert STTConfig.from_env().for_live().code_switching is True
