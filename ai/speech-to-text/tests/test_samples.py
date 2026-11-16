"""Runs the real model on audio placed in samples/. Skipped when no samples exist.

Only checks that non-empty Arabic text with valid timestamps is produced;
accuracy must be evaluated manually against a reference transcript.
"""
import re
from pathlib import Path

import pytest

from stt import STTConfig, Transcriber

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
AUDIO = sorted(p for p in SAMPLES.glob("*") if p.suffix.lower() in {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"})


@pytest.mark.skipif(not AUDIO, reason="no sample audio in samples/")
@pytest.mark.parametrize("audio", AUDIO, ids=lambda p: p.name)
def test_sample_transcription(audio, tmp_path):
    t = Transcriber(STTConfig.from_env()).transcribe_file(audio)
    assert t.segments, "no speech recognised"
    assert re.search(r"[؀-ۿ]", t.full_text), "no Arabic characters in output"
    assert all(0 <= s.start <= s.end for s in t.segments)
    t.save(tmp_path / f"{audio.stem}.txt")
