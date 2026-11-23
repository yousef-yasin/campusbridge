# Lecture Assistant API Contract (DRAFT)

**Status: draft, not agreed and not implemented.** This is a proposal from the AI team for
review by the Web team. Today `ai/lecture-assistant` is a Python library and CLI only; no HTTP
service exists yet. Paths, field names and limits below are open for discussion.

## Important: lecture text and questions leave the server

| What | Where it goes |
|---|---|
| Lecture chunks (at indexing) and questions | Google, Gemini embeddings (`gemini-embedding-2`) |
| The question, the retrieved chunks and the last 3 exchanges | Google, Gemini text models |

On the free tier Google states that content is used to improve its products. Whether this is
acceptable for course material and student questions, or the paid tier is needed, is an open
question for both teams.

## Overview

The assistant answers a student's question **only from the indexed lectures of the courses
that student is enrolled in**, and names the file and page or slide of every statement.

- Base path: `/api/ai/assistant`
- Request and response bodies: JSON, UTF-8
- The backend (ASP.NET Core) calls the service; the browser never calls it directly.
- **Authorization is the backend's job:** it decides which courses a student may search and sends
  them in `courses`. The AI service trusts this list and searches nothing else.
- The Gemini API key is server configuration and never appears in requests, responses or logs.

## POST `/api/ai/assistant/index`

Index (or re-index) one lecture file of a course. Called by the backend when an instructor
uploads or replaces a file. It can take minutes for a long file, so it is proposed as a job.

Request:

```json
{
  "course": "STAT101",
  "file_id": "a1b2c3",
  "file_name": "CLT_Chapter2.pptx",
  "file_url": "https://backend.internal/files/a1b2c3",
  "ocr": true,
  "describe_images": false
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `course` | string | yes | Course id. Search is limited by this value |
| `file_id` | string | yes | Stable id. Indexing the same id again replaces its chunks |
| `file_name` | string | yes | Shown in sources («CLT_Chapter2.pptx، سلايد 7») |
| `file_url` | string | yes | Where the service downloads the file (internal network) |
| `ocr` | bool | no | Read scanned pages and photos (page images sent to Google). Default `true` |
| `describe_images` | bool | no | Describe images not described yet (sent to Google). Default `false` |

Response `202 Accepted`: `{"job_id": "...", "status": "queued"}`. Then
`GET /api/ai/assistant/index/{job_id}`:

```json
{
  "status": "done",
  "course": "STAT101",
  "file_id": "a1b2c3",
  "units": 21,
  "chunks": 21,
  "embedded": 21,
  "warnings": []
}
```

`status`: `queued`, `running`, `done`, `failed`. When embeddings fail (quota, outage), the
file is still indexed for keyword search, `embedded` is lower than `chunks` and `warnings` says
so; indexing it again later fills the missing vectors.

`DELETE /api/ai/assistant/index/{course}/{file_id}` removes a file from the index.

Later: lecture transcripts (speech-to-text segments) are indexed the same way, with
`"transcript": [{"start": 0.0, "end": 4.2, "text": "..."}]` instead of `file_url`.

## POST `/api/ai/assistant/ask`

Request:

```json
{
  "question": "متى يصبح توزيع المعاينة طبيعياً؟",
  "courses": ["STAT101", "CS210"],
  "conversation_id": "9f3c2a71b0de",
  "file_id": null,
  "language": "mixed"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `question` | string | yes | Proposed limit: 500 characters |
| `courses` | string[] | yes | The student's courses, decided by the backend |
| `conversation_id` | string | no | From a previous answer, for follow-up questions (last 3 exchanges). Omit to start a new conversation |
| `file_id` | string | no | Limits «اشرح سلايد 7» and «لخص المحاضرة» to one file. Without it, a course with several files gets `status: "clarify"` |
| `language` | string | no | `ar`, `en`, `mixed` (`CB_EXPLAIN_LANGUAGE`). Default: server setting |

Response `200 OK`:

```json
{
  "question": "متى يصبح توزيع المعاينة طبيعياً؟",
  "status": "answered",
  "intent": "question",
  "answer": "عندما يكون حجم العينة 30 أو أكثر ... [CLT_Chapter2.pptx، سلايد 16]",
  "speech": "جواب تلقائي: عندما يكون حجم العينة 30 أو أكثر ... المصادر: CLT_Chapter2.pptx، سلايد 16.",
  "sources": [
    {"type": "lecture", "course": "STAT101", "file": "CLT_Chapter2.pptx", "unit": 16,
     "unit_type": "slide", "title": "Central Limit Theorem", "blocks": ["b1", "b2"], "from": ["text", "image"]}
  ],
  "problems": [],
  "conversation_id": "9f3c2a71b0de",
  "language": "mixed"
}
```

| `status` | Meaning | What the student hears |
|---|---|---|
| `answered` | Answer from the lectures, every statement with a source, all checks passed | `speech` |
| `needs_review` | Answered, but a number, English term or glossary meaning is not in the retrieved lectures, or a sentence has no source. `problems` lists why | `speech` (it says the answer may need checking) |
| `not_found` | The lectures do not contain the answer (STU-20). The text model is not called when no chunk matches well enough | «هذا غير موجود في محاضرات المساق.» |
| `clarify` | «اشرح سلايد 7» or «لخص المحاضرة» matches several files: `answer` lists them | `answer` |
| `unavailable` | No key, quota, no internet, or the service is busy. Never an HTTP 500 | A clear message, e.g. «المساعد لا يستطيع الإجابة الآن: انتهت حصة الطلبات المجانية حالياً…» |

`intent`: `question`, `slide` (STU-17 «اشرح سلايد رقم 7»), `summary` (STU-18 «لخص المحاضرة»),
`term` (STU-19 «اشرح مصطلح …», starts with the glossary meaning; its source has
`"type": "glossary"`).

`speech` is ready for the text-to-speech API (`POST /api/ai/tts/synthesize`): it starts with
«جواب تلقائي:», has no bracketed citations, and ends with the sources.

Optional for the instructor view: `"debug": true` adds `chunks`, the retrieved chunks with their
scores (`similarity`, `bm25`, `coverage`).

## Saved questions and answers

Every question is saved with its conversation id, courses, answer, status, sources and time,
**without the student's identity**, so instructors can see what is asked and review
`needs_review` answers. The conversation id is random. Whether the backend links it to a student
(for the student's own history) is a backend decision, stored on the backend side.

## Errors

| HTTP | When |
|---|---|
| 400 | Missing `question` or `courses`, question too long, unknown `language` |
| 503 | The vector store (database) is unreachable |

AI failures (quota, outage, no key) are not HTTP errors: they return `200` with
`status: "unavailable"`.

## Open questions

1. Free or paid Gemini tier for course material and student questions.
2. Who triggers indexing: on upload, or a nightly job.
3. Should `needs_review` answers be shown to the student at once, or held for the instructor?
4. Retention of saved questions.
