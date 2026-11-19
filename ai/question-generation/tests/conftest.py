import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for k in [k for k in os.environ if k.startswith(("QUESTIONS_", "READER_")) or
              k in ("GEMINI_API_KEY", "CB_EXPLAIN_LANGUAGE")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("QUESTIONS_CACHE_DIR", str(tmp_path / "questions"))
    monkeypatch.setenv("QUESTIONS_ENV_FILE", str(tmp_path / "no.env"))        # never the real key
    monkeypatch.setenv("READER_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("READER_IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("READER_DESCRIPTIONS_DIR", str(tmp_path / "descriptions"))
    monkeypatch.setenv("READER_OCR_DIR", str(tmp_path / "ocr"))

    def no_network(*args, **kwargs):
        raise AssertionError("test tried to reach Gemini; inject a fake engine")
    from google import genai
    monkeypatch.setattr(genai, "Client", no_network)


class FakeEngine:
    """Stands in for cb_shared.GeminiText: prepared answers, records the prompts."""
    model = "fake-text"
    last_model = "fake-text"

    def __init__(self, *answers, error=None):
        self.answers, self.error, self.prompts = list(answers), error, []
        self.notes = []

    def generate_json(self, prompt, schema):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return dict(self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)])
