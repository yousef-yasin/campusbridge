"""Finding the other CampusBridge AI modules (they are folders under ai/, not installed packages)."""
import os
import sys
from pathlib import Path

AI = Path(__file__).resolve().parents[3]          # ai/

SOURCES = {"document-reader": "src", "narrator": "src", "lecture-summarization": "src",
           "question-generation": "src", "text-to-speech": "src", "shared": "src"}


def use_module(name: str) -> Path:
    """Put ai/<name>/src on sys.path (once) and return it. CB_AI_DIR overrides the ai/ folder."""
    root = Path(os.environ.get("CB_AI_DIR") or AI)
    path = root / name / SOURCES.get(name, "src")
    if not path.is_dir():
        raise ImportError(f"CampusBridge module '{name}' not found at {path}")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path
