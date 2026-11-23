"""Gemini embeddings, with a cache by text and model. Text is sent to Google's servers.

Two kinds of documents and queries:
- gemini-embedding-2: no task_type; the task goes in the text ("title: ... | text: ..." for a
  document, "task: question answering | query: ..." for a question). One Content per text, since a
  plain list of strings is embedded as one combined input.
- gemini-embedding-001: task_type RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY; vectors below 3072
  dimensions must be normalised by the caller.
Every vector is L2-normalised here, so cosine similarity is a dot product.

Vectors of different models (or dimensions) cannot be compared, so there is no model chain for
embeddings: a 500/503/504 is retried on the same model, and when the service stays unavailable the
caller falls back to keyword search.
"""
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from cb_shared import AIBusyError, AIError, AILimitError, AIQuotaError, AIUnavailableError, get_key, scrub

from .config import EmbeddingConfig


def normalise(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def query_text(question: str, model: str) -> str:
    return f"task: question answering | query: {question}" if _prefix_style(model) else question


def _prefix_style(model: str) -> bool:
    return not model.endswith("-001")


class EmbeddingCache:
    """One JSON-lines file per model and size: {"sha256": ..., "vector": [...]} per line."""

    def __init__(self, folder, model: str, dimensions: int):
        self.path = Path(folder) / f"{model}-{dimensions}.jsonl"
        self._data: Optional[Dict[str, List[float]]] = None

    @staticmethod
    def key(kind: str, text: str) -> str:
        return hashlib.sha256(f"{kind}\n{text}".encode("utf-8")).hexdigest()

    def _load(self) -> Dict[str, List[float]]:
        if self._data is None:
            self._data = {}
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    try:
                        row = json.loads(line)
                        self._data[row["sha256"]] = row["vector"]
                    except (ValueError, KeyError):
                        continue                        # a broken line is ignored, not fatal
        return self._data

    def get(self, key: str) -> Optional[List[float]]:
        return self._load().get(key)

    def put(self, items: Dict[str, List[float]]) -> None:
        if not items:
            return
        data = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for key, vector in items.items():
                data[key] = vector
                f.write(json.dumps({"sha256": key, "vector": [round(v, 6) for v in vector]}) + "\n")


class GeminiEmbedder:
    """embed_documents(texts) / embed_query(question) -> normalised vectors (cached)."""

    def __init__(self, config: Optional[EmbeddingConfig] = None, client=None):
        self.config = config or EmbeddingConfig()
        self.model = self.config.model
        self.dimensions = self.config.dimensions
        self.cache = EmbeddingCache(self.config.cache_dir, self.model, self.dimensions)
        self._client = client
        self.calls = 0

    # --- public ------------------------------------------------------------------------
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return self._embed(list(texts), "document")

    def embed_query(self, question: str) -> List[float]:
        return self._embed([query_text(question, self.model)], "query")[0]

    # --- inside ------------------------------------------------------------------------
    def _embed(self, texts: List[str], kind: str) -> List[List[float]]:
        keys = [EmbeddingCache.key(kind, t) for t in texts]
        out: List[Optional[List[float]]] = [self.cache.get(k) for k in keys]
        todo = [i for i, v in enumerate(out) if v is None]
        if todo:
            key = get_key("GEMINI_API_KEY", self.config.env_files)
            client = self._get_client(key)
            for start in range(0, len(todo), self.config.batch):
                batch = todo[start:start + self.config.batch]
                vectors = self._request(client, key, [texts[i] for i in batch], kind)
                fresh = {}
                for i, vector in zip(batch, vectors):
                    out[i] = normalise(vector)
                    fresh[keys[i]] = out[i]
                self.cache.put(fresh)
        return out                                                         # type: ignore[return-value]

    def _get_client(self, key: str):
        if self._client is not None:
            return self._client
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise AIUnavailableError(f"google-genai is not installed: {exc}") from exc
        if not key:
            raise AIUnavailableError("GEMINI_API_KEY is not set (environment, or one of: "
                                     + ", ".join(self.config.env_files) + ")")
        from cb_shared.gemini_text import http_options
        return genai.Client(api_key=key, http_options=http_options(self.config.timeout))

    def _request(self, client, key: str, texts: List[str], kind: str) -> List[List[float]]:
        from google.genai import types
        if _prefix_style(self.model):
            contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
            config = types.EmbedContentConfig(output_dimensionality=self.dimensions)
        else:
            contents = texts
            config = types.EmbedContentConfig(output_dimensionality=self.dimensions,
                                              task_type="RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT")
        pauses = list(self.config.retry_pauses)
        for attempt in range(len(pauses) + 1):
            if self.calls >= self.config.max_calls:
                raise AILimitError(f"limit of {self.config.max_calls} embedding requests per run reached")
            self.calls += 1
            try:
                response = client.models.embed_content(model=self.model, contents=contents, config=config)
                vectors = [list(e.values) for e in response.embeddings or []]
                if len(vectors) != len(texts):
                    raise AIError(f"{self.model} returned {len(vectors)} embeddings for {len(texts)} texts")
                return vectors
            except AIError:
                raise
            except Exception as exc:
                error = self._error(exc, key)
                if isinstance(error, AIBusyError) and attempt < len(pauses):
                    time.sleep(pauses[attempt])
                    continue
                raise error from None
        raise AIBusyError(f"{self.model}: no answer")

    def _error(self, exc: Exception, key: str) -> AIError:
        code = getattr(exc, "code", None)
        detail = scrub(f"{type(exc).__name__}: {getattr(exc, 'message', None) or exc}", key)[:300]
        if code == 429:
            return AIQuotaError(f"{self.model}: quota or rate limit exceeded (429): {detail}")
        if code in (401, 403):
            return AIUnavailableError(f"Gemini rejected the API key ({code}): {detail}")
        module = type(exc).__module__
        if isinstance(exc, (OSError, TimeoutError)) or module.startswith(("httpx", "httpcore", "aiohttp")):
            if "timeout" in type(exc).__name__.lower() or "Timeout" in detail:
                return AIBusyError(f"{self.model}: no answer in {self.config.timeout} s: {detail}")
            return AIUnavailableError(f"Gemini unreachable (internet required): {detail}")
        if isinstance(code, int) and code >= 500:
            return AIBusyError(f"{self.model}: service error ({code}): {detail}")
        return AIError(f"{self.model}: {detail}")
