"""CampusBridge lecture assistant (RAG): answers a student's question from the course's lectures.

Index: text units (cb_shared.units) -> chunks -> Gemini embeddings -> a vector store.
Ask: hybrid search (embeddings + BM25 with Arabic normalisation, glossary expansion, only the
student's courses) -> a Gemini answer from the retrieved chunks only, with sources -> checks.
Lecture text and questions are sent to Google's Gemini servers.
"""
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[3] / "shared" / "src"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from .config import AssistantConfig                                  # noqa: E402
from .chunks import Chunk, chunk_units                               # noqa: E402
from .embeddings import EmbeddingCache, GeminiEmbedder               # noqa: E402
from .store import LocalStore, PgVectorStore, VectorStore, open_store   # noqa: E402
from .search import HybridSearch, Hit                                # noqa: E402
from .history import QALog                                           # noqa: E402
from .answer import Assistant, Answer                                # noqa: E402
from .indexer import Indexer                                         # noqa: E402

__all__ = ["AssistantConfig", "Chunk", "chunk_units", "EmbeddingCache", "GeminiEmbedder", "VectorStore",
           "LocalStore", "PgVectorStore", "open_store", "HybridSearch", "Hit", "QALog", "Assistant",
           "Answer", "Indexer"]
