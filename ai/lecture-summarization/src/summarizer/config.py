"""Settings (SUMMARY_* environment variables) and the shared explanation language."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from cb_shared import GeminiTextConfig

_ROOT = Path(__file__).resolve().parents[2]          # ai/lecture-summarization


def language_rules(mode=None):
    """(mode, instruction) from the shared CB_EXPLAIN_LANGUAGE setting (cb_shared.explain)."""
    from cb_shared.explain import INSTRUCTIONS, explain_language
    mode = explain_language(mode)
    return mode, INSTRUCTIONS[mode]


@dataclass
class SummaryConfig:
    language: str = ""                                   # "" = CB_EXPLAIN_LANGUAGE, else mixed
    cache_dir: str = str(_ROOT / "summaries")            # reviewable JSON, git-ignored
    min_words: int = 25                                  # shorter pages get no summary
    ai: GeminiTextConfig = field(default_factory=GeminiTextConfig)

    @classmethod
    def from_env(cls) -> "SummaryConfig":
        e = os.environ.get
        env_files = [str(_ROOT / ".env"), str(_ROOT.parent / "document-reader" / ".env")]
        return cls(language=e("CB_EXPLAIN_LANGUAGE", ""), cache_dir=e("SUMMARY_CACHE_DIR", cls.cache_dir),
                   min_words=int(e("SUMMARY_MIN_WORDS", cls.min_words)),
                   ai=GeminiTextConfig.from_env("SUMMARY", env_files))
