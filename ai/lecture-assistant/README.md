# Lecture assistant (RAG) (CampusBridge AI)

Answers a blind or visually impaired student's questions **only from the lectures of the
student's courses**, and names the file and page or slide of every statement. When the lectures
do not have the answer it says «هذا غير موجود في محاضرات المساق.» (STU-20) instead of inventing
one. The answer comes with text ready for text-to-speech, starting with «جواب تلقائي».

**Lecture text and questions are sent to Google** (Gemini embeddings and text models). On the
free tier, Google states that content is used to improve its products.

```
lecture-assistant/
├── requirements.txt           # document-reader + shared (google-genai)
├── sql/pgvector.sql           # the production table (PostgreSQL + pgvector)
├── src/assistant/
│   ├── chunks.py              # text units -> chunks with their metadata
│   ├── embeddings.py          # GeminiEmbedder (gemini-embedding-2) + cache
│   ├── store.py               # VectorStore: LocalStore (JSON file), PgVectorStore
│   ├── indexer.py             # file -> units -> chunks -> embeddings -> store
│   ├── arabic.py              # normalisation and words for keyword search
│   ├── search.py              # hybrid search: embeddings + BM25, glossary expansion, threshold
│   ├── answer.py              # Assistant.ask(): intents, the answer, checks
│   ├── speech.py              # «جواب تلقائي», fixed messages
│   ├── history.py             # QALog: saved questions and answers (no personal data)
│   └── __main__.py            # CLI
└── tests/
```

## Indexing

- **Input:** the generic text units of `ai/shared` (`cb_shared.units`). From a lecture file,
  document-reader gives the text, the image descriptions already made (phase 2), and the OCR
  text of scanned pages and photos (`--ocr`). Lecture transcripts (speech-to-text) use the same
  units (`from_transcript`), so they can be indexed later with `Indexer.index_units`.
- **Chunks:** one slide or page per chunk. A page over 350 words is split by whole blocks into
  parts of about 250 words, and each part starts with the last block of the previous one.
- **Each chunk keeps:**
  - the course and the file (name and title);
  - the page or slide number, its title and its block ids;
  - the language (`ar`, `en`, `mixed`);
  - where its text comes from: `text`, `image` (an image description), `ocr` or `transcript`.
- **Embeddings:** `gemini-embedding-2` at 768 dimensions. Checked in Google's embeddings, models
  and pricing pages on 2026-11-23:
  - the latest embedding model, for over 100 languages;
  - up to 8,192 input tokens;
  - free of charge on the free tier (no free-tier rate limits are published: see AI Studio);
  - vectors normalised by the model at 768, 1536 and 3072 dimensions.
  - It takes no `task_type`. The task goes in the text: `title: … | text: …` for a chunk,
    `task: question answering | query: …` for a question.
  - A plain list of strings is embedded as **one** combined input, so each text is sent as its own
    `Content`.
  - `gemini-embedding-001` also works (`ASSISTANT_EMBEDDING_MODEL`, with task types).
- **Embeddings cache:** `embeddings-cache/<model>-<size>.jsonl` (git-ignored), by the sha256 of
  the text. Indexing the same file again makes no request.
- **Store:** one interface (`VectorStore`) with two versions.
  - `LocalStore` is one JSON file (`index/store.json`, git-ignored), for development and tests.
  - `PgVectorStore` is PostgreSQL with pgvector, for production. The table is in
    `sql/pgvector.sql`, and it needs `psycopg` and `ASSISTANT_DATABASE_URL`. It is tested with a
    fake connection only.
  - The store records the embedding model: vectors of another model are refused, because they
    cannot be compared.
- **When embeddings fail** (no key, quota, offline), the file is still indexed for keyword search,
  with a warning. Indexing it again later adds the vectors.

## Search

- **Hybrid:** by meaning (cosine similarity of the embeddings) and by words (BM25), fused by
  reciprocal rank.
- **Arabic normalisation for the words:**
  - diacritics and tatweel removed;
  - أ/إ/آ/ٱ → ا, ؤ → و, ئ → ي, ة → ه, ى → ي;
  - Arabic-Indic digits → 0-9;
  - the article and one-letter prefixes removed (ال، وال، بال، لل…);
  - common words left out.
- **Glossary expansion:** the shared glossary (`ai/shared/glossary/terms.json`) adds the Arabic
  meaning of an English term in the question, and the English term of an Arabic meaning. So
  «توزيع المعاينة» finds a slide that says "sampling distribution".
- **Only the student's courses** are searched: `--course` (CLI) or `courses` (API).
- **Threshold:** a chunk matches when its similarity is at least `ASSISTANT_MIN_SIMILARITY` (0.68)
  or it holds at least `ASSISTANT_MIN_COVERAGE` (0.6) of the question's words. A glossary term
  and its meaning count as one word, and «وتعيش» counts as «تعيش». When no retrieved chunk
  matches, the answer is «هذا غير موجود في محاضرات المساق» and **the text model is not called**.
  - Tuned on the 12 files of `ai/samples-in` with `gemini-embedding-2` at 768 dimensions on
    2026-11-23.
  - Chunks that answer the question scored 0.70 to 0.84.
  - Unrelated questions scored 0.54 to 0.63 on their best chunk: «ما هي عاصمة أستراليا؟»,
    «كيف أطبخ المقلوبة؟», and "What is a firewall?" on the information-security chapter, which
    does not explain firewalls.
  - Another model or size needs new values.
- **Without embeddings** (no key, quota, offline), keyword search still works.

## Answers

- **Gemini text** (the `ai/shared` client: retries on 500/503/504, then the next model) gets the
  question and the retrieved chunks, tagged `[S1]`, `[S2]`…
  - It must use only those chunks, put the tag after every sentence, and copy numbers exactly.
  - It may combine and compare facts that the chunks state (for example, the difference between
    two terms that two slides define).
  - When a chunk's text states a fact, the text wins over the labels of a figure description.
  - Tags become «[CLT.pptx، سلايد 16]» in the answer.
- **Language:** `CB_EXPLAIN_LANGUAGE` (`ar`, `en`, `mixed`), and the glossary meanings of the
  terms in the chunks are given as rules.
- **Checks after the answer**, any failure → `needs_review` with the reasons in `problems`:
  - every number must be in the retrieved chunks or the question;
  - every English word (`ar`/`mixed`) must be in the retrieved chunks or the question;
  - a meaning written next to a glossary term must match the glossary;
  - every sentence needs a source tag, and every tag must be a retrieved chunk.
- **Special requests:**
  - «اشرح سلايد رقم 7» / «explain slide 7» (STU-17): that slide is fetched directly, without
    search.
  - «لخص المحاضرة» (STU-18): lecture-summarization summarises the file (page summaries, then a
    file summary, cached in `ai/lecture-summarization/summaries/`).
  - «اشرح مصطلح …» / «ما معنى …» (STU-19): the glossary meaning first, then how the lectures use
    the term. With no lecture chunk, the glossary meaning alone.
  - With several files in the student's courses, the slide and summary requests answer
    `clarify` with the file names, unless `--file` is given.
- **Follow-up questions:** the last 3 exchanges of the conversation go into the prompt, only to
  understand the question. The previous question also helps the search.
- **Result:**
  - `answer`, `sources` (file, page/slide, title, blocks, kind of source), `chunks` (the
    retrieved chunks and their scores);
  - `status`: `answered`, `not_found` or `needs_review`, and also `clarify` and `unavailable`;
  - `speech`: «جواب تلقائي: … المصادر: …». Spoken sources use the file's title and group its
    pages: «المصادر: Chapter 1 - Information Security، صفحات 4 و5 و6».
- **Saved questions:** `qa-log/log.json` (git-ignored; a database table later) through `QALog`.
  It holds a random conversation id, the courses, the question, the answer, the status, the
  sources and the time. **There is no student id or name.**
- **Failures never crash:**
  - no key → «مفتاح خدمة الذكاء الاصطناعي غير مضبوط»;
  - quota (429) → «انتهت حصة الطلبات المجانية حالياً»;
  - no internet → «لا يوجد اتصال بالإنترنت»;
  - busy → «خدمة الذكاء الاصطناعي مشغولة الآن».
  - Each gives `status: "unavailable"`.

## Use

From `ai/lecture-assistant`, with Python 3.12:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
$env:PYTHONPATH="src"                                   # bash: export PYTHONPATH=src
python -m assistant index ../samples-in/CLT.pptx --course STAT101
python -m assistant index scan.pdf --course STAT101 --ocr          # read scanned pages (sent to Google)
python -m assistant ask "متى يصبح توزيع المعاينة طبيعياً؟" --course STAT101
python -m assistant ask "وكم يجب أن يكون حجم العينة؟" --course STAT101 --conversation <id>
python -m assistant ask "اشرح سلايد رقم 16" --course STAT101 --speech
python -m assistant courses
.venv/Scripts/python -m pytest -q
```

In code:

```python
from assistant import Assistant, AssistantConfig, GeminiEmbedder, Indexer, open_store
cfg = AssistantConfig.from_env()
store = open_store(cfg)
Indexer(store, GeminiEmbedder(cfg.embedding), cfg).index_file("lecture.pptx", "STAT101")
answer = Assistant(store, GeminiEmbedder(cfg.embedding), config=cfg).ask("…", ["STAT101"])
answer.status, answer.answer, answer.sources, answer.speech
```

## Settings

| Variable | Default | |
|---|---|---|
| `CB_EXPLAIN_LANGUAGE` | `mixed` | `ar`, `en`, `mixed` |
| `ASSISTANT_STORE` | `local` | `local` or `pgvector` |
| `ASSISTANT_STORE_PATH` | `index/store.json` | local store file |
| `ASSISTANT_DATABASE_URL` | | pgvector |
| `ASSISTANT_EMBEDDING_MODEL` / `_DIMENSIONS` | `gemini-embedding-2` / `768` | |
| `ASSISTANT_EMBEDDING_MAX_CALLS` | `200` | embedding requests per run |
| `ASSISTANT_MODELS` | shared chain | text models, e.g. `gemini-3.5-flash-lite,gemini-4-hydrogen` |
| `ASSISTANT_MAX_CALLS` | `30` | text requests per run |
| `ASSISTANT_TOP_K` | `5` | chunks given to the model |
| `ASSISTANT_MIN_SIMILARITY` | `0.55` | see "Threshold" |
| `ASSISTANT_MIN_COVERAGE` | `0.5` | see "Threshold" |
| `ASSISTANT_LOG_PATH` | `qa-log/log.json` | saved questions |
| `CB_GEMINI_IPV4` | off | `1`: connect to Google over IPv4 only (see below) |

**IPv6:** on a network where IPv6 to Google does not work, the first request of each process
waited about 170 s for IPv6 to fail (measured here). `CB_GEMINI_IPV4=1` (in `ai/shared`)
connects over IPv4 only: the same request took 0.7 s. Document-reader's OCR and image
descriptions (indexing with `--ocr`) use the same option.

`GEMINI_API_KEY`: the module's own `.env`, else `ai/document-reader/.env` (git-ignored, never
printed). The API draft for the Web team is `docs/api-contracts/lecture-assistant.md`.

## Tests

The tests use fake embeddings, a fake text model and a fake database connection, so there is no
network; a real Gemini client is blocked.

## Limitations

- The checks catch invented numbers, invented English terms, wrong glossary meanings and
  sentences without a source. They do not catch every wrong statement in Arabic, or an
  incomplete answer.
  - In the trial, «ما نسبة البيانات بين انحراف معياري واحد تحت المتوسط وفوقه؟» was answered
    «34.1% تحت المتوسط و34.1% فوقه» from the figure of slide 16. That is correct, but it is not
    the total: slide 17 says about 68%, and the answer did not use it.
- The threshold was tuned on the test files of `ai/samples-in` only.
- The local store compares the question with every chunk. That is fine for a few thousand
  chunks; production should use pgvector.
- The pgvector store is tested with a fake connection only, not a real database.
