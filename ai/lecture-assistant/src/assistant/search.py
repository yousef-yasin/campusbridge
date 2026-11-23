"""Hybrid search: meaning (embeddings) + words (BM25 with Arabic normalisation), fused by rank.

- Only the courses the student is allowed to see are searched.
- The question is expanded with the shared glossary: an English term found in the question adds
  its Arabic meaning, and an Arabic meaning adds the English term, so an Arabic question finds an
  English slide and the other way round.
- A threshold says whether the best chunks really match. When they do not, the caller answers
  "not in the lectures" without calling the text model.
- If the question cannot be embedded (no key, quota, no internet), keyword search still works.
"""
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .arabic import with_variants, words
from .chunks import Chunk
from .store import VectorStore

RRF_K = 60          # reciprocal rank fusion constant (the usual value)


@dataclass
class Hit:
    chunk: Chunk
    score: float = 0.0                 # fused score (reciprocal ranks)
    similarity: Optional[float] = None  # cosine similarity of the embeddings
    bm25: float = 0.0
    coverage: float = 0.0              # share of the question's words found in the chunk
    methods: List[str] = field(default_factory=list)

    def strong(self, min_similarity: float, min_coverage: float) -> bool:
        return (self.similarity is not None and self.similarity >= min_similarity) or self.coverage >= min_coverage

    def to_dict(self) -> Dict:
        c = self.chunk
        return {"id": c.id, "course": c.course, "file": c.file, "unit": c.unit, "unit_type": c.unit_type,
                "title": c.title, "blocks": c.block_ids, "language": c.language, "sources": c.sources,
                "score": round(self.score, 4), "similarity": None if self.similarity is None else round(self.similarity, 3),
                "bm25": round(self.bm25, 2), "coverage": round(self.coverage, 2), "methods": self.methods}


@dataclass
class SearchResult:
    hits: List[Hit]
    confident: bool                    # at least one hit is a strong match
    expansions: List[str]              # glossary pairs used, "term = meaning"
    notes: List[str]                   # e.g. "semantic search unavailable: ..."


class BM25:
    def __init__(self, docs: Sequence[List[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avg = (sum(self.lengths) / len(docs)) if docs else 0.0
        n = len(docs)
        df = Counter(w for d in self.docs for w in d)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: Iterable[str]) -> List[float]:
        query = list(dict.fromkeys(query))
        out = []
        for doc, length in zip(self.docs, self.lengths):
            s = 0.0
            for w in query:
                tf = doc.get(w)
                if tf:
                    s += self.idf[w] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
            out.append(s)
        return out


class HybridSearch:
    def __init__(self, store: VectorStore, embedder=None, glossary=None, config=None):
        from .config import AssistantConfig
        self.store, self.embedder, self.glossary = store, embedder, glossary
        self.config = config or AssistantConfig()

    # --- glossary expansion ------------------------------------------------------------
    def expand(self, question: str) -> List[Dict[str, str]]:
        """Glossary entries the question uses, in English or by their Arabic meaning."""
        if not self.glossary:
            return []
        found = {e.term.lower(): e for e in self.glossary.find(question)}
        for entry in self.glossary.entries.values():
            if entry.term.lower() not in found and entry.matches(question):
                found[entry.term.lower()] = entry
        return [{"term": e.term, "meaning": e.meaning, "accepted": list(e.accepted)} for e in found.values()]

    @staticmethod
    def _concepts(question: str, expansions: List[Dict[str, str]]) -> List[Set[str]]:
        """The question's words; a glossary term and its meaning are one concept (either one counts)."""
        q = words(question)
        concepts: List[Set[str]] = []
        used: Set[str] = set()
        for e in expansions:
            forms = [words(e["term"]), words(e["meaning"])] + [words(a) for a in e["accepted"]]
            if any(f and set(f) <= set(q) for f in forms):
                concepts.append({" ".join(f) for f in forms if f})
                for f in forms:
                    used.update(w for w in f if w in q)
        concepts += [{w} for w in dict.fromkeys(q) if w not in used]
        return concepts

    @staticmethod
    def _coverage(concepts: List[Set[str]], chunk_words: Set[str]) -> float:
        if not concepts:
            return 0.0
        found = sum(1 for c in concepts if any(all(w in chunk_words for w in form.split()) for form in c))
        return found / len(concepts)

    # --- search ------------------------------------------------------------------------
    def search(self, question: str, courses: Iterable[str], context: str = "",
               k: Optional[int] = None) -> SearchResult:
        cfg = self.config
        k = k or cfg.top_k
        courses = list(courses)
        notes: List[str] = []
        chunks = self.store.chunks(courses)
        expansions = self.expand(question + " " + context)
        if not chunks:
            return SearchResult([], False, [f"{e['term']} = {e['meaning']}" for e in expansions],
                                ["no indexed lectures for these courses"])
        extra = " ".join(f"{e['term']} {e['meaning']}" for e in expansions)
        query_words = words(f"{question} {context} {extra}")
        hits: Dict[str, Hit] = {}

        # words (BM25)
        bm25 = BM25([with_variants(words(f"{c.title}\n{c.text}")) for c in chunks]).scores(query_words)
        ranked = sorted(range(len(chunks)), key=lambda i: bm25[i], reverse=True)
        for rank, i in enumerate([i for i in ranked if bm25[i] > 0][:cfg.candidates]):
            hit = hits.setdefault(chunks[i].id, Hit(chunks[i]))
            hit.bm25 = bm25[i]
            hit.score += 1 / (RRF_K + rank + 1)
            hit.methods.append("keyword")

        # meaning (embeddings)
        if self.embedder is not None:
            try:
                vector = self.embedder.embed_query(f"{context} {question}".strip() + (f" ({extra})" if extra else ""))
                for rank, (chunk, sim) in enumerate(self.store.nearest(vector, courses, cfg.candidates)):
                    hit = hits.setdefault(chunk.id, Hit(chunk))
                    hit.similarity = sim
                    hit.score += 1 / (RRF_K + rank + 1)
                    hit.methods.append("semantic")
            except Exception as exc:                      # no key, quota, offline: keyword search only
                notes.append(f"semantic search unavailable, keyword search only: {exc}")

        concepts = self._concepts(question, expansions)
        for hit in hits.values():
            hit.coverage = self._coverage(concepts, set(with_variants(words(f"{hit.chunk.title}\n{hit.chunk.text}"))))
        best = sorted(hits.values(), key=lambda h: h.score, reverse=True)[:k]
        confident = any(h.strong(cfg.min_similarity, cfg.min_coverage) for h in best)
        return SearchResult(best, confident, [f"{e['term']} = {e['meaning']}" for e in expansions], notes)

    def unit(self, courses: Iterable[str], number: int, file: Optional[str] = None) -> List[Chunk]:
        """All chunks of page/slide `number` (STU-17), in the given file or the only file that has it."""
        found = [c for c in self.store.chunks(list(courses)) if c.unit == number and (file is None or c.file == file)]
        return sorted(found, key=lambda c: (c.file, c.part))
