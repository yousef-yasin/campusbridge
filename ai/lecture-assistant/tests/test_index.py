import json

import pytest

from conftest import OLIVE, STATS, FakeEmbedder, unit
from assistant import AssistantConfig, GeminiEmbedder, Indexer, LocalStore, chunk_units
from assistant.arabic import language_of, normalize, words
from assistant.config import EmbeddingConfig
from assistant.store import PgVectorStore, StoreError
from cb_shared import AIUnavailableError


def test_arabic_normalisation_and_words():
    assert normalize("أَشْجارُ الزَّيْتونِ ٣٠ إِلى مدرسةٍ") == "اشجار الزيتون 30 الي مدرسه"
    assert words("والإحصاء بالعيّنة") == words("الاحصاء العينه") == ["احصاء", "عينه"]
    assert words("What are the sample means?") == ["sample", "mean"]
    assert language_of("Central Limit Theorem") == "en" and language_of("نظرية النهاية") == "ar"
    assert language_of("يوضح الشكل Central Limit Theorem") == "mixed"


def test_one_chunk_per_slide_with_its_metadata():
    chunks = chunk_units(STATS + [], "STAT101", "CLT.pptx", "Sampling Distributions")
    assert [c.unit for c in chunks] == [1, 2, 3]
    c = chunks[2]
    assert (c.course, c.file, c.file_title, c.unit_type, c.title) == \
        ("STAT101", "CLT.pptx", "Sampling Distributions", "slide", "Central Limit Theorem")
    assert c.block_ids == ["b1", "b2", "b3"] and c.language == "en" and c.sources == ["text", "image"]
    assert c.embedding_text().startswith("title: Central Limit Theorem | text: Central Limit Theorem\n")
    ocr = chunk_units(OLIVE, "AGR100", "olive.docx")[1]
    assert ocr.sources == ["text", "ocr"] and ocr.language == "ar"


def test_a_long_page_is_split_by_blocks_with_overlap():
    blocks = [("paragraph", " ".join([f"word{i}"] * 100)) for i in range(7)]
    chunks = chunk_units([unit(4, *blocks, unit_type="page")], "C", "long.pdf", max_words=350, part_words=250)
    # 100-word blocks, about 250 words per part, the last block of a part starts the next one
    assert [c.block_ids for c in chunks] == [["b1", "b2"], ["b2", "b3"], ["b3", "b4"], ["b4", "b5"],
                                             ["b5", "b6"], ["b6", "b7"]]
    assert all(c.unit == 4 and c.parts == 6 for c in chunks) and [c.part for c in chunks] == [1, 2, 3, 4, 5, 6]
    assert len({c.id for c in chunks}) == 6
    short = chunk_units([unit(5, *blocks[:3], unit_type="page")], "C", "long.pdf")
    assert len(short) == 1 and short[0].block_ids == ["b1", "b2", "b3"]


def test_local_store_keeps_files_per_course_and_refuses_another_model(tmp_path):
    cfg = AssistantConfig.from_env()
    store = LocalStore(cfg.store_path)
    Indexer(store, FakeEmbedder(), cfg).index_units(STATS, "STAT101", "CLT.pptx")
    Indexer(store, FakeEmbedder(), cfg).index_units(STATS[:1], "STAT101", "CLT.pptx")      # re-index replaces
    again = LocalStore(cfg.store_path)
    assert [c.unit for c in again.chunks(["STAT101"])] == [1] and again.chunks(["OTHER"]) == []
    assert again.model == "fake-embedding" and len(again.chunks()[0].vector) == 64
    other = FakeEmbedder()
    other.model = "another-model"
    with pytest.raises(StoreError, match="rebuild"):
        Indexer(again, other, cfg).index_units(STATS, "STAT101", "CLT.pptx")


def test_failed_embeddings_keep_the_file_searchable_by_words():
    cfg = AssistantConfig.from_env()
    store = LocalStore(cfg.store_path)
    indexer = Indexer(store, FakeEmbedder(fail=AIUnavailableError("GEMINI_API_KEY is not set")), cfg)
    report = indexer.index_units(STATS, "STAT101", "CLT.pptx")
    assert report["chunks"] == 2 and report["embedded"] == 0 and report["skipped_title_units"] == [1]
    assert "keyword search only" in indexer.warnings[0]
    assert all(c.vector is None for c in store.chunks())


class _Embedding:
    def __init__(self, values):
        self.values = values


class FakeClient:
    """google-genai client stand-in: records the requests, can fail first with a status code."""

    def __init__(self, fail_codes=()):
        self.requests, self.fail_codes = [], list(fail_codes)
        self.models = self

    def embed_content(self, model, contents, config):
        self.requests.append((model, contents, config))
        if self.fail_codes:
            error = Exception("unavailable")
            error.code = self.fail_codes.pop(0)
            raise error
        return type("R", (), {"embeddings": [_Embedding([3.0, 4.0] + [0.0] * 2) for _ in contents]})()


def _embedder(tmp_path, client, **kw):
    cfg = EmbeddingConfig(cache_dir=str(tmp_path / "emb"), dimensions=4, retry_pauses=(0, 0), **kw)
    return GeminiEmbedder(cfg, client=client)


def test_gemini_embedder_sends_one_content_per_text_normalises_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = FakeClient()
    emb = _embedder(tmp_path, client)
    vectors = emb.embed_documents(["title: a | text: one", "title: b | text: two"])
    assert vectors[0] == pytest.approx([0.6, 0.8, 0.0, 0.0])
    model, contents, config = client.requests[0]
    assert model == "gemini-embedding-2" and len(contents) == 2 and contents[0].parts[0].text == "title: a | text: one"
    assert config.output_dimensionality == 4 and config.task_type is None
    query = emb.embed_query("what?")
    assert client.requests[1][1][0].parts[0].text == "task: question answering | query: what?" and query
    # a second embedder with the same cache makes no request
    again = _embedder(tmp_path, FakeClient())
    again._client.fail_codes = [500] * 9
    assert again.embed_documents(["title: a | text: one"]) == [vectors[0]]


def test_gemini_embedder_001_uses_task_types(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = FakeClient()
    _embedder(tmp_path, client, model="gemini-embedding-001").embed_query("q")
    assert client.requests[0][1] == ["q"] and client.requests[0][2].task_type == "RETRIEVAL_QUERY"


def test_gemini_embedder_retries_503_then_stops_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = FakeClient(fail_codes=[503, 503])
    assert _embedder(tmp_path, client).embed_documents(["x"]) and len(client.requests) == 3
    from cb_shared import AIBusyError, AIQuotaError
    with pytest.raises(AIBusyError):
        _embedder(tmp_path, FakeClient(fail_codes=[503] * 3)).embed_documents(["y"])
    with pytest.raises(AIQuotaError):
        _embedder(tmp_path, FakeClient(fail_codes=[429])).embed_documents(["z"])


def test_missing_key_is_a_clear_error(tmp_path):
    with pytest.raises(AIUnavailableError, match="GEMINI_API_KEY is not set"):
        GeminiEmbedder(EmbeddingConfig(cache_dir=str(tmp_path), env_files=[str(tmp_path / "no.env")])).embed_query("q")


class FakeDB:
    """Records SQL; answers the info query and one nearest-neighbour row."""

    def __init__(self):
        self.sql, self.commits = [], 0

    def cursor(self):
        db = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, args=()):
                db.sql.append((" ".join(sql.split()), args))

            def fetchone(self):
                return None

            def fetchall(self):
                data = json.dumps({**chunk_units(STATS, "STAT101", "CLT.pptx")[1].to_dict(), "vector": None})
                return [(data, 0.91)]
        return Cur()

    def commit(self):
        self.commits += 1


def test_pgvector_store_uses_the_sql_table_and_course_filter():
    db = FakeDB()
    store = PgVectorStore("postgresql://test", connect=lambda url: db)
    chunks = chunk_units(STATS, "STAT101", "CLT.pptx")
    for c in chunks:
        c.vector = [0.1] * 4
    store.set_model("fake", 4)
    store.replace_file("STAT101", "CLT.pptx", chunks)
    hits = store.nearest([0.1] * 4, ["STAT101"], 3)
    assert hits[0][0].unit == 2 and hits[0][1] == 0.91
    sql = [s for s, _ in db.sql]
    assert any(s.startswith("DELETE FROM assistant_chunks WHERE course") for s in sql)
    assert sum(s.startswith("INSERT INTO assistant_chunks") for s in sql) == 3
    nearest = next((s, a) for s, a in db.sql if "<=>" in s)
    assert "course = ANY(%s)" in nearest[0] and nearest[1][1] == ["STAT101"]
    table = (__import__("pathlib").Path(__file__).resolve().parents[1] / "sql" / "pgvector.sql").read_text(encoding="utf-8")
    assert "vector(768)" in table and "vector_cosine_ops" in table


def test_title_pages_and_university_ids_are_not_indexed():
    from assistant.privacy import filter_units, has_university_id
    title = unit(1, ("heading", "قاعدة الطباق والمقابلة في اللغة العربية"),
                 ("paragraph", "رحلة استكشافية في عالم المحسنات البديعية"),
                 ("paragraph", "الطالبة: سارة أحمد"), ("paragraph", "شعبة: (1)"),
                 ("paragraph", "الرقم الجامعي: 202012345"))
    body = unit(2, ("heading", "ما هو الطباق؟"),
                ("paragraph", "الطباق هو الجمع بين كلمة ونقيضها في سياق واحد لإبراز التضاد والمعنى في النص."),
                ("paragraph", "Student ID 202199887 wrote this note."))
    cfg = AssistantConfig.from_env()
    store = LocalStore(cfg.store_path)
    report = Indexer(store, FakeEmbedder(), cfg).index_units([title, body], "AR101", "tibaq.pptx")
    assert report["skipped_title_units"] == [1] and report["dropped_id_blocks"] == 1
    text = "\n".join(c.text for c in store.chunks())
    assert "سارة" not in text and "202012345" not in text and "202199887" not in text
    assert [c.unit for c in store.chunks()] == [2] and "الطباق هو الجمع" in text
    # a first page with real content, and a one-page file, are kept
    assert filter_units(OLIVE)[1] == [] and filter_units(STATS)[1] == [1]
    assert filter_units([title])[1] == []
    assert has_university_id("رقم الطالب 1234") and has_university_id("University No. 55")
    assert not has_university_id("In 2022 there were 20 million new cases") and not has_university_id("201 متقدماً")
