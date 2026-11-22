import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for k in [k for k in os.environ if k.endswith(("_MODELS", "_MAX_CALLS")) or k in ("GEMINI_API_KEY", "CB_EXPLAIN_LANGUAGE")]:
        monkeypatch.delenv(k)

    def no_network(*args, **kwargs):
        raise AssertionError("test tried to reach Gemini; inject a fake client")
    from google import genai
    monkeypatch.setattr(genai, "Client", no_network)
