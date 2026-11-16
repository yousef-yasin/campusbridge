import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FakeModel:
    """Stands in for faster_whisper.WhisperModel."""

    def __init__(self, segments=None, error=None):
        self.segments = segments or [(0.0, 2.0, " مرحبا بكم في المحاضرة "), (2.0, 4.5, "اليوم نتحدث عن الخوارزميات")]
        self.error = error
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        if self.error:
            raise self.error
        return iter(SimpleNamespace(start=s, end=e, text=t) for s, e, t in self.segments), None


@pytest.fixture(autouse=True)
def clean_stt_state(monkeypatch):
    """Isolate tests from the caller's STT_* variables and the shared model slot."""
    import os
    from stt import transcriber
    for k in [k for k in os.environ if k.startswith("STT_")]:
        monkeypatch.delenv(k)
    monkeypatch.setattr(transcriber, "_shared", {"key": None, "model": None})


@pytest.fixture
def fake_model():
    return FakeModel()
