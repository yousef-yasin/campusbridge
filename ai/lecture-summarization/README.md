# Lecture summarization (CampusBridge AI)

Summaries for blind and visually impaired students. For each page or slide it gives:
- a short summary (2 to 3 sentences);
- 3 to 5 key points, each linked to the block it comes from;
- the page's terms with their meanings.

A summary of the whole file is then built from the page summaries. Questions are in
`ai/question-generation`; the Gemini client, the input units, the cache and the checks are in
`ai/shared`.

**Text is sent to Google's Gemini servers** (free tier: content is used to improve Google's
products).

```bash
# from ai/lecture-summarization, with PYTHONPATH=src
python -m summarizer file ../samples-in/CLT.pptx --pages 7,16            # mixed (default)
python -m summarizer --speech file ../samples-in/CLT.pptx --pages 16
python -m summarizer file photo.jpg --ocr                                 # a photo of a page
python -m summarizer --lang en --json file lecture.pdf --pages 1-5
python -m summarizer transcript lecture-segments.json --minutes 5         # speech-to-text, later
```

```python
from summarizer import summarize_units, summary_speech, file_summary_speech
from cb_shared import from_pages

results, file_summary, warnings = summarize_units(from_pages(pages), language="mixed", title="CLT")
print(summary_speech(results[0]))        # «ملخص تلقائي: ...», key points, terms
```

## Input

The input is numbered text units with numbered blocks (`cb_shared.units`):
- **Pages of a file** from document-reader: text, tables, chart data, speaker notes, described
  images, and OCR text of scanned pages and photos. `load_units` uses image descriptions already
  cached; `--describe` and `--ocr` make new ones.
- **Parts of a lecture transcript**, through `from_transcript`, for speech-to-text later.

## Result per unit

`{"unit", "label", "status", "review", "summary", "points": [{"text", "block"}],
"terms": [{"term", "meaning"}], "problems", "model", "cached", "cache_file"}`.

`status` is one of:
- `ok`;
- `needs_review`: a check failed, see `problems`;
- `manual`: a person's text is used;
- `skipped`: a title slide, or fewer than 25 words (`SUMMARY_MIN_WORDS`);
- `unavailable`: no key, quota, offline, every model busy, or the request limit; see `reason`.

## Rules given to the model

- Only the text of this page: no outside knowledge, examples or definitions the text does not
  give.
- Numbers are copied exactly, never calculated.
- Each key point names its block (`b3`).
- A term is written as in the text, with the meaning the text gives. A term the text does not
  explain is left out.
- Language: `CB_EXPLAIN_LANGUAGE` (`ar`, `en`, `mixed`; `--lang`), the same setting and wording
  as the image descriptions. In `mixed`, an English term comes first with its Arabic meaning.
- The file summary uses only the page summaries.

## Glossary

In `ar` and `mixed` modes, the meanings of the glossary terms found on the page
(`ai/shared/glossary/terms.json`, for example sampling distribution = توزيع المعاينة) are given
to the model with the instruction to use exactly those meanings. After generation, every
«term (Arabic)» or «Arabic (term)» is compared with the glossary; a different meaning marks the
result `needs_review`. Prompt version 2.

## Checks after generation

If any check below fails, the result is marked `needs_review`:
- every number in the summary, points and meanings must be in the page text (document-reader's
  number check, through `ai/shared`);
- in `ar` and `mixed` modes, every English word must appear in the page; in `en` mode, every
  term must;
- every point must link to a block that exists.

The file summary is checked against the text of all pages.

## Cache and review

There is one JSON file per page text (sha256), model, language and prompt version, in
`summaries/` (`SUMMARY_CACHE_DIR`, git-ignored). Each file holds:
- `result`, the automatic answer;
- `review`, which is `draft` until a person sets it to `approved`;
- `manual` (`summary`, `points`, `terms`): any non-empty field replaces the automatic one. The
  status is then `manual`, speech says «ملخص:» instead of «ملخص تلقائي:», and the checks are not
  applied.

## Speech

- A page summary is read as «ملخص تلقائي: …», then «النقاط المهمة:», then «المصطلحات:» with the
  terms and their meanings.
- The file summary is read as «ملخص تلقائي للملف: …».
- In `en` mode: "Automatic summary: …".
- The narrator reads page summaries after each page (`--summaries`), or on request with
  «لخّصلي الصفحة» (`Navigator.summarize()`).

## Failures

A missing key, quota, no internet, every model busy, or the per-run limit (`SUMMARY_MAX_CALLS`,
default 30) never stop the caller. The unit is marked `unavailable`, one warning explains why,
and no more requests are made in that run.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `SUMMARY_MODELS` | `gemini-3.5-flash-lite,gemini-4-hydrogen,gemini-3.8-flash` | model chain (see `ai/shared`) |
| `SUMMARY_MAX_CALLS` | 30 | requests per run |
| `SUMMARY_TIMEOUT` | 90 | seconds per request |
| `SUMMARY_MIN_WORDS` | 25 | shorter pages get no summary |
| `SUMMARY_CACHE_DIR` | `summaries/` | reviewable results |
| `SUMMARY_ENV_FILE` | | `.env` with `GEMINI_API_KEY`; by default the module's own `.env`, then `ai/document-reader/.env` |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

The tests use a fake engine and generated files, and a real Gemini client is blocked.

## Limitations

- The checks catch invented numbers and invented English terms, not every wrong statement in
  Arabic: review important summaries.
- One request per page for the summary and another for the questions.
