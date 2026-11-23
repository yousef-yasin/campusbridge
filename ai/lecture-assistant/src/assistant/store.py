"""Vector store: one interface, two versions.

- LocalStore: a JSON file (development and tests). Similarity is computed in memory.
- PgVectorStore: PostgreSQL with the pgvector extension (production); the table is in
  sql/pgvector.sql. Needs psycopg (not installed by default) and ASSISTANT_DATABASE_URL.

Every store records the embedding model and size: vectors of another model cannot be compared,
so indexing with another model is refused until the store is rebuilt.
"""
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .chunks import Chunk


class StoreError(RuntimeError):
    pass


class VectorStore:
    """The interface the indexer and the search use."""
    model: Optional[str] = None
    dimensions: Optional[int] = None

    def set_model(self, model: str, dimensions: int) -> None:
        if self.model and (self.model, self.dimensions) != (model, dimensions):
            raise StoreError(f"the store holds {self.model}/{self.dimensions} vectors, not {model}/{dimensions}: "
                             f"rebuild it (assistant index --rebuild) to change the model")
        self.model, self.dimensions = model, dimensions

    def replace_file(self, course: str, file: str, chunks: Sequence[Chunk]) -> None:
        raise NotImplementedError

    def chunks(self, courses: Optional[Iterable[str]] = None) -> List[Chunk]:
        raise NotImplementedError

    def nearest(self, vector: Sequence[float], courses: Iterable[str], k: int) -> List[Tuple[Chunk, float]]:
        raise NotImplementedError

    def courses(self) -> Dict[str, List[str]]:
        """{course: [files]}"""
        out: Dict[str, List[str]] = {}
        for c in self.chunks():
            files = out.setdefault(c.course, [])
            if c.file not in files:
                files.append(c.file)
        return out


class LocalStore(VectorStore):
    def __init__(self, path):
        self.path = Path(path)
        self._chunks: List[Chunk] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise StoreError(f"cannot read the index {self.path}: {exc}") from None
            self.model, self.dimensions = data.get("model"), data.get("dimensions")
            self._chunks = [Chunk.from_dict(c) for c in data.get("chunks", [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "model": self.model, "dimensions": self.dimensions,
                "chunks": [c.to_dict() for c in self._chunks]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def replace_file(self, course: str, file: str, chunks: Sequence[Chunk]) -> None:
        self._chunks = [c for c in self._chunks if not (c.course == course and c.file == file)] + list(chunks)
        self.save()

    def chunks(self, courses: Optional[Iterable[str]] = None) -> List[Chunk]:
        if courses is None:
            return list(self._chunks)
        allowed = set(courses)
        return [c for c in self._chunks if c.course in allowed]

    def nearest(self, vector: Sequence[float], courses: Iterable[str], k: int) -> List[Tuple[Chunk, float]]:
        scored = [(c, sum(a * b for a, b in zip(vector, c.vector))) for c in self.chunks(courses) if c.vector]
        return sorted(scored, key=lambda x: x[1], reverse=True)[:k]


class PgVectorStore(VectorStore):
    """PostgreSQL + pgvector (sql/pgvector.sql). Cosine distance with the <=> operator."""

    def __init__(self, url: str, connect=None):
        if not url:
            raise StoreError("ASSISTANT_DATABASE_URL is not set")
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise StoreError("pgvector store needs psycopg (pip install 'psycopg[binary]')") from exc
            connect = psycopg.connect
        self.db = connect(url)
        row = self._one("SELECT model, dimensions FROM assistant_index_info WHERE id = 1")
        if row:
            self.model, self.dimensions = row

    def _one(self, sql, args=()):
        with self.db.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()

    @staticmethod
    def _vec(vector) -> str:
        return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"

    def set_model(self, model: str, dimensions: int) -> None:
        super().set_model(model, dimensions)
        with self.db.cursor() as cur:
            cur.execute("INSERT INTO assistant_index_info (id, model, dimensions) VALUES (1, %s, %s) "
                        "ON CONFLICT (id) DO NOTHING", (model, dimensions))
        self.db.commit()

    def replace_file(self, course: str, file: str, chunks: Sequence[Chunk]) -> None:
        with self.db.cursor() as cur:
            cur.execute("DELETE FROM assistant_chunks WHERE course = %s AND file = %s", (course, file))
            for c in chunks:
                data = c.to_dict()
                data.pop("vector")
                cur.execute("INSERT INTO assistant_chunks (id, course, file, unit, unit_type, language, data, embedding) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
                            (c.id, c.course, c.file, c.unit, c.unit_type, c.language,
                             json.dumps(data, ensure_ascii=False), self._vec(c.vector) if c.vector else None))
        self.db.commit()

    def _rows(self, sql, args) -> List[Chunk]:
        with self.db.cursor() as cur:
            cur.execute(sql, args)
            return [Chunk.from_dict(dict(json.loads(r[0]) if isinstance(r[0], str) else r[0], vector=None))
                    for r in cur.fetchall()]

    def chunks(self, courses: Optional[Iterable[str]] = None) -> List[Chunk]:
        if courses is None:
            return self._rows("SELECT data FROM assistant_chunks ORDER BY course, file, unit", ())
        return self._rows("SELECT data FROM assistant_chunks WHERE course = ANY(%s) ORDER BY course, file, unit",
                          (list(courses),))

    def nearest(self, vector: Sequence[float], courses: Iterable[str], k: int) -> List[Tuple[Chunk, float]]:
        with self.db.cursor() as cur:
            cur.execute("SELECT data, 1 - (embedding <=> %s::vector) FROM assistant_chunks "
                        "WHERE course = ANY(%s) AND embedding IS NOT NULL "
                        "ORDER BY embedding <=> %s::vector LIMIT %s",
                        (self._vec(vector), list(courses), self._vec(vector), k))
            return [(Chunk.from_dict(dict(json.loads(r[0]) if isinstance(r[0], str) else r[0], vector=None)), float(r[1]))
                    for r in cur.fetchall()]


def open_store(config) -> VectorStore:
    if config.store == "pgvector":
        return PgVectorStore(config.database_url)
    if config.store != "local":
        raise StoreError(f"unknown store '{config.store}' (local or pgvector)")
    return LocalStore(config.store_path)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)
