"""Settings (ASSISTANT_* environment variables) and the shared explanation language."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from cb_shared import GeminiTextConfig

ROOT = Path(__file__).resolve().parents[2]          # ai/lecture-assistant


def language_rules(mode=None):
    """(mode, instruction) from the shared CB_EXPLAIN_LANGUAGE setting (cb_shared.explain)."""
    from cb_shared.explain import INSTRUCTIONS, explain_language
    mode = explain_language(mode)
    return mode, INSTRUCTIONS[mode]


@dataclass
class EmbeddingConfig:
    # Checked in Google's embeddings, models and pricing pages on 2026-11-23: gemini-embedding-2 is
    # the latest model (over 100 languages, up to 8,192 input tokens, free of charge on the free
    # tier, normalised output at 768/1536/3072 dimensions). No task_type for this model: the task
    # goes in the text ("task: search result | query: ..." / "title: ... | text: ...").
    model: str = "gemini-embedding-2"
    dimensions: int = 768
    batch: int = 20                       # texts per request
    timeout: int = 60                     # seconds per request
    retry_pauses: tuple = (5.0, 15.0)     # waits after a 500/503/504
    max_calls: int = 200                  # embedding requests per run (0 = none)
    cache_dir: str = str(ROOT / "embeddings-cache")
    env_files: list = field(default_factory=lambda: [str(ROOT / ".env"),
                                                     str(ROOT.parent / "document-reader" / ".env")])


@dataclass
class AssistantConfig:
    language: str = ""                                   # "" = CB_EXPLAIN_LANGUAGE, else mixed
    store: str = "local"                                 # "local" (a file) or "pgvector"
    store_path: str = str(ROOT / "index" / "store.json")
    database_url: str = ""                               # pgvector: ASSISTANT_DATABASE_URL
    log_path: str = str(ROOT / "qa-log" / "log.json")
    # chunks
    max_words: int = 350                                 # a longer page is split by blocks
    part_words: int = 250                                # words per part of a long page
    overlap_blocks: int = 1                              # blocks repeated at the start of the next part
    # search
    top_k: int = 5
    candidates: int = 20                                 # per method, before fusion
    min_similarity: float = 0.68                         # cosine (gemini-embedding-2, 768): below this a chunk does not match
    min_coverage: float = 0.6                            # share of the question's words found in a chunk
    history_turns: int = 3
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    ai: GeminiTextConfig = field(default_factory=GeminiTextConfig)

    @classmethod
    def from_env(cls) -> "AssistantConfig":
        e = os.environ.get
        cfg = cls()
        env_files = [str(ROOT / ".env"), str(ROOT.parent / "document-reader" / ".env")]
        cfg.language = e("CB_EXPLAIN_LANGUAGE", "")
        cfg.store = e("ASSISTANT_STORE", cfg.store)
        cfg.store_path = e("ASSISTANT_STORE_PATH", cfg.store_path)
        cfg.database_url = e("ASSISTANT_DATABASE_URL", "")
        cfg.log_path = e("ASSISTANT_LOG_PATH", cfg.log_path)
        cfg.top_k = int(e("ASSISTANT_TOP_K", cfg.top_k))
        cfg.min_similarity = float(e("ASSISTANT_MIN_SIMILARITY", cfg.min_similarity))
        cfg.min_coverage = float(e("ASSISTANT_MIN_COVERAGE", cfg.min_coverage))
        emb = cfg.embedding
        emb.model = e("ASSISTANT_EMBEDDING_MODEL", emb.model)
        emb.dimensions = int(e("ASSISTANT_EMBEDDING_DIMENSIONS", emb.dimensions))
        emb.max_calls = int(e("ASSISTANT_EMBEDDING_MAX_CALLS", emb.max_calls))
        emb.cache_dir = e("ASSISTANT_EMBEDDINGS_DIR", emb.cache_dir)
        emb.env_files = env_files
        if e("ASSISTANT_ENV_FILE"):                          # one explicit .env file (tests: never the real key)
            emb.env_files = [e("ASSISTANT_ENV_FILE")]
        cfg.ai = GeminiTextConfig.from_env("ASSISTANT", env_files)
        return cfg
