"""Indexing: a lecture file (or transcript units) -> chunks -> embeddings -> the store."""
from pathlib import Path
from typing import Dict, List, Optional

from cb_shared import TextUnit

from .chunks import Chunk, chunk_units
from .config import AssistantConfig
from .store import VectorStore


class Indexer:
    def __init__(self, store: VectorStore, embedder, config: Optional[AssistantConfig] = None):
        self.store, self.embedder = store, embedder
        self.config = config or AssistantConfig()
        self.warnings: List[str] = []

    def index_units(self, units: List[TextUnit], course: str, file: str, file_title: str = "") -> Dict:
        cfg = self.config
        chunks = chunk_units(units, course, file, file_title, cfg.max_words, cfg.part_words, cfg.overlap_blocks)
        embedded = 0
        if chunks and self.embedder is not None:
            self.store.set_model(self.embedder.model, self.embedder.dimensions)
            try:
                vectors = self.embedder.embed_documents([c.embedding_text() for c in chunks])
                for chunk, vector in zip(chunks, vectors):
                    chunk.vector = vector
                embedded = len(chunks)
            except Exception as exc:          # no key, quota, offline: the file is still searchable by words
                self.warnings.append(f"{file}: embeddings failed, keyword search only until it is indexed again: {exc}")
        self.store.replace_file(course, file, chunks)
        return {"course": course, "file": file, "title": file_title, "units": len(units), "chunks": len(chunks),
                "embedded": embedded, "split_units": sorted({c.unit for c in chunks if c.parts > 1}),
                "sources": sorted({s for c in chunks for s in c.sources})}

    def index_file(self, path, course: str, ocr: bool = False, describe: bool = False,
                   language: Optional[str] = None) -> Dict:
        """A lecture file through document-reader. Cached image descriptions are used; ocr and
        describe send page images to Google."""
        from cb_shared.documents import load_units
        units, title, warnings = load_units(path, None, ocr, describe, language)
        self.warnings += [f"{Path(path).name}: {w}" for w in warnings]
        return self.index_units(units, course, Path(path).name, title or "")


def units_from_chunks(chunks: List[Chunk]) -> List[TextUnit]:
    """The units of a file rebuilt from its chunks (overlapping blocks once), for summaries."""
    from cb_shared import UnitBlock
    units: Dict[int, TextUnit] = {}
    for c in sorted(chunks, key=lambda c: (c.unit, c.part)):
        unit = units.setdefault(c.unit, TextUnit(c.unit, c.unit_type, [], c.title, meta=dict(c.meta)))
        seen = {b.id for b in unit.blocks}
        unit.blocks += [UnitBlock(b["id"], b["kind"], b["text"], b.get("origin", "text"))
                        for b in c.blocks if b["id"] not in seen]
    return [units[n] for n in sorted(units)]
