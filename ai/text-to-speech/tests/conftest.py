import io
import os
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Read at import time, before the autouse fixture clears TTS_* variables.
ALLOW_NETWORK = os.environ.get("TTS_TEST_EDGE") == "1"
ALLOW_GEMINI = os.environ.get("TTS_TEST_GEMINI") == "1"


def make_wav(seconds: float = 0.1, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


def wav_info(data: bytes):
    """(sample_rate, frames) of WAV bytes."""
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getframerate(), w.getnframes()


class FakeEngine:
    """Stands in for PiperEngine/EdgeEngine: 0.1 s of audio per segment, no model needed."""
    ext = "wav"

    def __init__(self, error=None, rates=None, name="piper", single_voice="", raw_text=False,
                 max_chars=0):
        self.name = name
        self.single_voice = single_voice
        self.raw_text = raw_text
        self.max_chars = max_chars
        self.error = error
        self.rates = rates or {"ar": 16000, "en": 16000}
        self.calls = []

    def voice_for(self, lang):
        return self.single_voice or f"fake-{lang}"

    def synthesize(self, text, lang, speed):
        self.calls.append((text, lang, speed))
        if self.error:
            raise self.error
        return make_wav(0.1, self.rates[lang])

    def join(self, clips):
        from tts.engines import join_wav
        return join_wav(clips)


class FakeGeminiClient:
    """Stands in for google.genai.Client: records requests, returns audio or raises."""

    def __init__(self, data=None, mime="audio/wav", error=None):
        self.data = make_wav(0.1, 24000) if data is None else data
        self.mime = mime
        self.error = error
        self.requests = []
        self.models = self

    def generate_content(self, model, contents, config):
        part = contents[0].parts[0]
        self.requests.append({
            "model": model, "text": part.text,
            "style": part.speech_metadata.style if part.speech_metadata else None,
            "voice": config.speech_config.voice_config.prebuilt_voice_config.voice_name,
            "modalities": config.response_modalities,
        })
        if self.error:
            raise self.error
        inline = SimpleNamespace(data=self.data, mime_type=self.mime)
        content = SimpleNamespace(parts=[SimpleNamespace(inline_data=inline)])
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


@pytest.fixture(autouse=True)
def clean_tts_state(monkeypatch, tmp_path):
    """Isolate tests from the caller's TTS_* variables, API key, loaded voices, cache, phrases."""
    from tts import engines
    for k in [k for k in os.environ if k.startswith("TTS_") or k == "GEMINI_API_KEY"]:
        monkeypatch.delenv(k)
    if not ALLOW_GEMINI:                 # never read the developer's real .env in unit tests
        monkeypatch.setenv("TTS_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TTS_PHRASES_FILE", str(tmp_path / "data" / "phrases.json"))
    monkeypatch.setattr(engines, "_voices", {})

    def no_network(*args, **kwargs):     # unit tests must never call the online service
        raise AssertionError("test tried to reach edge-tts; inject a fake engine")
    import edge_tts
    if not ALLOW_NETWORK:
        monkeypatch.setattr(edge_tts, "Communicate", no_network)
    if not ALLOW_GEMINI:
        from google import genai
        monkeypatch.setattr(genai, "Client", no_network)


@pytest.fixture
def cfg(tmp_path):
    from tts import TTSConfig
    return TTSConfig(cache_dir=str(tmp_path / "cache"), voices_dir=str(tmp_path / "voices"),
                     phrases_file=str(tmp_path / "data" / "phrases.json"),
                     env_file=str(tmp_path / "test.env"))


@pytest.fixture
def fake_engine():
    return FakeEngine()
