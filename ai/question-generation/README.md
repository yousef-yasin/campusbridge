# Question generation (CampusBridge AI)

Practice questions for blind and visually impaired students: 2 to 3 exam-style questions per
page or slide, each with a short answer linked to its page and block. The student hears the
question, thinks, then hears the answer (the narrator's «اسألني»).

**Text is sent to Google's Gemini servers** (free tier: content is used to improve Google's
products). The Gemini client, the input units, the cache and the checks are in `ai/shared`.

```bash
# from ai/question-generation, with PYTHONPATH=src
python -m questions file ../samples-in/CLT.pptx --pages 16,17
python -m questions file photo.jpg --ocr --speech
python -m questions transcript lecture-segments.json --minutes 5
python -m questions --lang en --json file lecture.pdf --pages 3
```

```python
from questions import QuestionGenerator, questions_speech, question_parts
from cb_shared import from_pages

results = QuestionGenerator(language="mixed").run(from_pages(pages))
for r in results:
    print(questions_speech(r))     # «سؤال: ...\nالجواب: ...»
```

## Result per unit

`{"unit", "label", "status", "review", "questions": [{"question", "answer", "block", "page",
"unit_type"}], "problems", "model", "cached", "cache_file"}`.

`status` is one of:
- `ok`;
- `needs_review`: a check failed, see `problems`;
- `manual`;
- `skipped`: a title slide, or fewer than 25 words (`QUESTIONS_MIN_WORDS`);
- `unavailable`: no key, quota, offline or limit, see `reason`.

## Rules given to the model

- Every question must be answerable from this page alone, and every answer must be stated on
  it. No outside knowledge.
- If the page does not support a good question, the model writes fewer questions, or none (an
  empty list is a valid answer). It never invents one.
- Short answers. Numbers are copied exactly, never calculated.
- Each answer names its block. The question asks about understanding (what, why, how, compare),
  and never about the title, page numbers or layout alone.
- At most 3 questions are kept.
- Language: `CB_EXPLAIN_LANGUAGE` (`ar`, `en`, `mixed`; `--lang`).

## Glossary

In `ar` and `mixed` modes, the meanings of the glossary terms found on the page
(`ai/shared/glossary/terms.json`, for example sampling distribution = توزيع المعاينة) are given
to the model with the instruction to use exactly those meanings. After generation, every
«term (Arabic)» or «Arabic (term)» is compared with the glossary; a different meaning marks the
result `needs_review`. Prompt version 2.

## Checks after generation

If any check below fails, the result is marked `needs_review`:
- every number must appear in the page text (document-reader's number check, through `ai/shared`);
- in `ar` and `mixed` modes, every English word must appear in the page;
- every answer must point to a block that exists.

## Cache and review

There is one JSON file per page text, model, language and prompt version, in `questions-cache/`
(`QUESTIONS_CACHE_DIR`, git-ignored). Each file has `review`, which is `draft` until a person
sets it to `approved`, and `manual.questions`. A non-empty manual list replaces the automatic one.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `QUESTIONS_MODELS` | `gemini-3.5-flash-lite,gemini-4-hydrogen,gemini-3.8-flash` | model chain |
| `QUESTIONS_MAX_CALLS` | 30 | requests per run |
| `QUESTIONS_TIMEOUT` | 90 | seconds per request |
| `QUESTIONS_ENV_FILE` | | `.env` with `GEMINI_API_KEY`; by default the module's own `.env`, then `ai/document-reader/.env` |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

The tests use a fake engine, and a real Gemini client is blocked.
