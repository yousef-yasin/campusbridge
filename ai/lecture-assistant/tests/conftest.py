import hashlib
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import assistant  # noqa: E402,F401  (puts ai/shared/src on the path)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for k in [k for k in os.environ if k.startswith(("ASSISTANT_", "SUMMARY_", "READER_")) or
              k in ("GEMINI_API_KEY", "CB_EXPLAIN_LANGUAGE", "CB_GLOSSARY_FILE")]:
        monkeypatch.delenv(k)
    for prefix in ("ASSISTANT", "SUMMARY", "READER"):
        monkeypatch.setenv(f"{prefix}_ENV_FILE", str(tmp_path / "no.env"))        # never the real key
    monkeypatch.setenv("ASSISTANT_STORE_PATH", str(tmp_path / "index" / "store.json"))
    monkeypatch.setenv("ASSISTANT_LOG_PATH", str(tmp_path / "qa-log" / "log.json"))
    monkeypatch.setenv("ASSISTANT_EMBEDDINGS_DIR", str(tmp_path / "embeddings"))
    monkeypatch.setenv("SUMMARY_CACHE_DIR", str(tmp_path / "summaries"))
    monkeypatch.setenv("READER_IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("READER_DESCRIPTIONS_DIR", str(tmp_path / "descriptions"))
    monkeypatch.setenv("READER_OCR_DIR", str(tmp_path / "ocr"))

    def no_network(*args, **kwargs):
        raise AssertionError("test tried to reach Gemini; inject a fake engine")
    from google import genai
    monkeypatch.setattr(genai, "Client", no_network)


# Words of both languages that mean the same thing get the same dimension, so the fake
# embeddings behave like multilingual ones.
SAME = {"توزيع": "distribution", "معاينه": "sampling", "متوسط": "mean", "طبيعي": "normal",
        "زيتون": "olive", "شجره": "tree", "اشجار": "tree", "عينه": "sample", "عينات": "sample"}


class FakeEmbedder:
    model, dimensions = "fake-embedding", 64

    def __init__(self, fail=None):
        self.fail, self.calls, self.queries = fail, 0, []

    def _vector(self, text):
        from assistant.arabic import words
        v = [0.0] * self.dimensions
        for w in words(text.split("|", 1)[-1]):
            w = SAME.get(w, w).rstrip("s")
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dimensions] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        self.calls += 1
        if self.fail:
            raise self.fail
        return [self._vector(t) for t in texts]

    def embed_query(self, question):
        self.queries.append(question)
        if self.fail:
            raise self.fail
        return self._vector(question)


class FakeEngine:
    """Stands in for cb_shared.GeminiText: prepared answers, records the prompts."""
    model = last_model = "fake-text"

    def __init__(self, *answers, error=None):
        self.answers, self.error, self.prompts, self.notes = list(answers), error, [], []

    def generate_json(self, prompt, schema):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        answer = self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]
        return dict(answer(prompt) if callable(answer) else answer)


def unit(number, *blocks, unit_type="slide", title=None):
    """A TextUnit from (kind, text[, origin]) tuples."""
    from cb_shared import TextUnit, UnitBlock
    made = [UnitBlock(f"b{i}", b[0], b[1], b[2] if len(b) > 2 else ("image" if b[0] == "image" else "text"))
            for i, b in enumerate(blocks, 1)]
    head = next((b.text for b in made if b.kind == "heading"), "")
    return TextUnit(number, unit_type, made, title if title is not None else head)


STATS = [
    unit(1, ("heading", "Sampling Distributions")),
    unit(2, ("heading", "Sampling distribution of the mean"),
         ("paragraph", "The sampling distribution of the mean is the distribution of all sample means "
                       "of size n taken from a population."),
         ("paragraph", "Its mean equals the population mean.")),
    unit(3, ("heading", "Central Limit Theorem"),
         ("paragraph", "When the sample size is at least 30, the sampling distribution of the mean is "
                       "approximately a normal distribution."),
         ("image", "Image: A histogram of 500 sample means shaped like a bell curve.")),
]
OLIVE = [
    unit(1, ("heading", "شجرة الزيتون"),
         ("paragraph", "تُزرع أشجار الزيتون في الأردن منذ آلاف السنين، وتعيش الشجرة أكثر من 500 عام."),
         unit_type="page"),
    unit(2, ("heading", "فوائد الزيت"), ("paragraph", "يستخدم زيت الزيتون في الطعام والصابون.", "ocr"),
         unit_type="page"),
]


@pytest.fixture
def built(tmp_path):
    """A local store with a statistics course and an olive course, indexed with fake embeddings."""
    from assistant import AssistantConfig, Indexer, LocalStore
    cfg = AssistantConfig.from_env()
    store = LocalStore(cfg.store_path)
    embedder = FakeEmbedder()
    indexer = Indexer(store, embedder, cfg)
    indexer.index_units(STATS, "STAT101", "CLT.pptx", "Sampling Distributions")
    indexer.index_units(OLIVE, "AGR100", "olive.docx", "شجرة الزيتون")
    cfg.min_similarity = 0.5
    return store, embedder, cfg
