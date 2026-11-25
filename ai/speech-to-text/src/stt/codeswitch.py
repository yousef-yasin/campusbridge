"""Arabic-English code-switching refinement, applied after the primary Arabic pass.

1. English re-pass: short segments written in Arabic script whose audio is confidently
   detected as English are re-transcribed with language="en" (fixes transliterations such
   as "Entities" -> "انتو تيز"). Timestamps are kept.
2. Gap recovery: speech found by VAD but not covered by any segment (English phrases the
   Arabic-forced decoder skipped) is transcribed in its detected language (Arabic or English).

Long mixed segments are left unchanged; their audio is detected as Arabic.
"""
import re
from typing import List

import numpy as np

from .transcript import Segment

SR = 16000
EN = "en"
MIN_PROB = 0.8          # language-detection confidence needed to act
MIN_REPASS_S = 0.5      # shorter clips give unreliable detection
MAX_REPASS_S = 4.0      # longer segments are mixed or Arabic; detection says Arabic
MIN_GAP_S = 0.4
GAP_PAD_S = 0.15
MIN_LOGPROB = -1.0
MAX_NO_SPEECH = 0.5

_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


def _detect(model, clip) -> dict:
    _, _, probs = model.detect_language(clip)
    return dict(probs)


def _transcribe(model, clip, language: str, beam_size: int) -> str:
    segs, _ = model.transcribe(clip, language=language, beam_size=beam_size, vad_filter=False,
                               condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs
                    if s.avg_logprob >= MIN_LOGPROB and s.no_speech_prob <= MAX_NO_SPEECH).strip()


def _clip(audio, start: float, end: float):
    return audio[max(0, int(start * SR)):int(end * SR)]


def _speech_regions(audio) -> List[tuple]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return [(r["start"] / SR, r["end"] / SR)
            for r in get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300))]


def _gaps(regions, segments) -> List[tuple]:
    covered = sorted((s.start, s.end) for s in segments)
    out = []
    for a, b in regions:
        cur = a
        for cs, ce in covered:
            if ce <= cur:
                continue
            if cs >= b:
                break
            if cs - cur >= MIN_GAP_S:
                out.append((cur, cs))
            cur = max(cur, ce)
        if b - cur >= MIN_GAP_S:
            out.append((cur, b))
    return out


def refine(model, audio: np.ndarray, segments: List[Segment], language: str,
           beam_size: int = 5) -> List[Segment]:
    """Return segments with English re-pass and gap recovery applied (timestamps relative to audio)."""
    out = []
    for s in segments:
        dur = s.end - s.start
        if _ARABIC.search(s.text) and MIN_REPASS_S <= dur <= MAX_REPASS_S:
            clip = _clip(audio, s.start, s.end)
            if _detect(model, clip).get(EN, 0.0) >= MIN_PROB:
                text = _transcribe(model, clip, EN, beam_size)
                if _LATIN.search(text):
                    s = Segment(s.start, s.end, text, s.slide)
        out.append(s)

    for a, b in _gaps(_speech_regions(audio), out):
        clip = _clip(audio, a - GAP_PAD_S, b + GAP_PAD_S)
        probs = _detect(model, clip)
        lang = max((language, EN), key=lambda l: probs.get(l, 0.0))
        if probs.get(lang, 0.0) >= MIN_PROB:
            text = _transcribe(model, clip, lang, beam_size)
            if text:
                out.append(Segment(round(a, 2), round(b, 2), text))
    return sorted(out, key=lambda s: s.start)
