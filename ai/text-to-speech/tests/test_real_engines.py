"""Runs the real engines. Skipped unless the voices / network / API key are available.

Gemini: runs only with TTS_TEST_GEMINI=1; it needs GEMINI_API_KEY in .env, uses the free
quota and sends the text to Google.
Piper: runs when both configured voice models are in voices/ (see README, "Voices").
edge-tts: runs only with TTS_TEST_EDGE=1, because it sends text to Microsoft's online service.

These tests only check that playable audio is produced; pronunciation quality
must be judged by listening.
"""
import io
import os
import wave
from pathlib import Path

import pytest

from tts import Synthesizer, TTSConfig

VOICES = Path(__file__).resolve().parents[1] / "voices"
RUN_EDGE = os.environ.get("TTS_TEST_EDGE") == "1"     # read before the autouse fixture clears TTS_*
RUN_GEMINI = os.environ.get("TTS_TEST_GEMINI") == "1"
TEXT = "مرحباً بكم في المحاضرة. اليوم عندنا 3 مواضيع عن machine learning. Thank you."


def _has_piper_voices() -> bool:
    cfg = TTSConfig()
    return all((VOICES / f"{v}.onnx").is_file() and (VOICES / f"{v}.onnx.json").is_file()
               for v in (cfg.piper_voice_ar, cfg.piper_voice_en))


@pytest.mark.skipif(not _has_piper_voices(), reason="Piper voice models not downloaded to voices/")
def test_piper_real_arabic_english(tmp_path):
    cfg = TTSConfig(engine="piper", voices_dir=str(VOICES), cache_dir=str(tmp_path / "cache"))
    out = Synthesizer(cfg).synthesize(TEXT, tmp_path / "piper")
    with wave.open(io.BytesIO(out.read_bytes()), "rb") as w:
        assert w.getnframes() / w.getframerate() > 2.0


@pytest.mark.skipif(not RUN_GEMINI, reason="set TTS_TEST_GEMINI=1 to call the Gemini API")
def test_gemini_real_arabic_english(tmp_path):
    cfg = TTSConfig(engine="gemini", fallback=False, cache_dir=str(tmp_path / "cache"))
    tts = Synthesizer(cfg)
    out = tts.synthesize(TEXT, tmp_path / "gemini")
    with wave.open(io.BytesIO(out.read_bytes()), "rb") as w:
        assert w.getframerate() == 24000 and w.getnframes() / w.getframerate() > 2.0
    assert tts.fallbacks == []


@pytest.mark.skipif(not RUN_EDGE, reason="set TTS_TEST_EDGE=1 to call the online edge-tts service")
def test_edge_real_arabic_english(tmp_path):
    cfg = TTSConfig(engine="edge", fallback=False, cache_dir=str(tmp_path / "cache"))
    tts = Synthesizer(cfg)
    assert tts.engine.single_voice == "en-AU-WilliamMultilingualNeural"
    out = tts.synthesize(TEXT, tmp_path / "edge")
    data = out.read_bytes()
    assert out.suffix == ".mp3" and len(data) > 5000 and tts.fallbacks == []
