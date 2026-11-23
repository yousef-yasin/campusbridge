# Shared AI utilities (CampusBridge AI)

Code used by more than one AI module (see `ai/README.md`): today `lecture-summarization` and
`question-generation`, and the narrator through them.

```
shared/
├── requirements.txt          # google-genai, pytest
├── src/cb_shared/
│   ├── gemini_text.py        # GeminiText: Gemini text client (JSON answers, retries, model chain, limit)
│   ├── units.py              # TextUnit / UnitBlock: the generic input; from_pages(), from_transcript()
│   ├── jobs.py               # UnitJob: per-unit loop (skip rules, cache, manual edits, checks, failures)
│   ├── cache.py              # ReviewCache: reviewable JSON (draft/approved, manual fields win)
│   ├── checks.py             # number check (document-reader's numbers.py) and English-word check
│   ├── glossary.py           # shared glossary: English term -> correct Arabic meaning, meaning check
│   ├── explain.py            # CB_EXPLAIN_LANGUAGE (ar / en / mixed): moved here from document-reader
│   ├── documents.py          # load_units(file, pages): a lecture file -> units, via document-reader
│   ├── keys.py               # GEMINI_API_KEY from the environment or .env files (never printed)
│   ├── paths.py              # use_module("document-reader"): find the sibling modules
│   └── errors.py             # AIError, AIUnavailableError, AIBusyError, AIQuotaError, AILimitError
├── glossary/terms.json      # the glossary data (sealed with sha256)
└── tests/
```

## Gemini text client

`GeminiText(GeminiTextConfig(...)).generate_json(prompt, schema) -> dict`. **Text is sent to
Google's servers.** On the free tier, Google states that content is used to improve its
products.

**Models.** Free-tier text models, checked in Google's pricing and models pages on 2026-11-19:
`gemini-4-hydrogen`, `gemini-3.8-flash`, `gemini-3.6-flash` and `gemini-3.5-flash-lite`. Google
recommends Hydrogen or 3.5 Flash-Lite for new projects. The default chain is
`gemini-3.5-flash-lite` → `gemini-4-hydrogen` → `gemini-3.8-flash`. On that day only Flash-Lite
answered a probe: Hydrogen gave 503, and 3.8/3.6 Flash timed out (504). Change the chain with
`<PREFIX>_MODELS` (for example `SUMMARY_MODELS=gemini-4-hydrogen,gemini-3.5-flash-lite`).

**When a request fails:**
- **500/503/504** are retried on the same model after 5 s and 15 s. The last try drops the JSON
  schema, then the next model is used. A note records the switch.
- **429** (quota) moves to the next model, since free-tier limits are per model.
- **No key, 401/403, or no internet** stop at once, because every model would fail the same way.

**IPv6:** on a network where IPv6 to Google does not work, the first request waits minutes for
the IPv6 connection to fail. `CB_GEMINI_IPV4=1` connects over IPv4 only (off by default).
`http_options(timeout)` builds the client settings; the lecture assistant's embeddings and
document-reader's image descriptions and OCR use it too.

**Settings and limit:**
- Calls are counted, and `max_calls` (`<PREFIX>_MAX_CALLS`, default 30) stops a run before it
  uses up the daily quota. 0 means no request at all.
- The key is read at request time from `GEMINI_API_KEY`, then from the module's own `.env`, then
  `ai/document-reader/.env`. `<PREFIX>_ENV_FILE` names one file, which the tests point to an empty
  temporary file.

## Text units (the input)

`TextUnit(number, unit_type, blocks, title, source, meta)` holds blocks with ids `b1`, `b2`, ...,
so results can point to where a fact comes from.

- **`from_pages(pages)`** takes document-reader pages: text, lists, tables, chart data, speaker
  notes, handwritten notes, OCR text, and described images ("Image: … Text in the image: …").
  References and undescribed or decorative images are left out.
- **`from_transcript(segments, seconds_per_unit=300)`** takes speech-to-text segments
  `[{"start", "end", "text"}]` and groups them into parts of about 5 minutes, for later use.
- **`unit.is_title_unit()`** recognises the first page or slide when it has only a title, or a
  title and a short subtitle.

## Checks

- **Numbers:** `unverified_numbers(generated, sources)` is document-reader's `numbers.py`, loaded
  from its file (standard library only). It checks digits and Arabic or English number words, by
  value.
- **English words:** `missing_english(generated, source)` lists English words (3+ letters) that
  the source never uses. Plurals of source words are accepted.

## Glossary

`glossary/terms.json` maps English technical terms to their correct Arabic meaning, for example
sampling distribution = توزيع المعاينة. It starts with the statistics, information security and
machine-learning terms of our test files: 47 terms, `CB_GLOSSARY_FILE` to use another file.

**Same format as the speech-to-text glossary** (`ai/speech-to-text/src/stt/glossary.py`,
unchanged). That glossary maps the Arabic-script spoken form of a term to the English term
(«الجوريثم» → algorithm), for correcting transcripts, and has no Arabic meanings.
- This file uses its schema 1: `course`, `version`, `sha256`, and `terms[]` with
  `term`/`kind`/`aliases`.
- It adds `meaning_ar`, `accepted_ar` (other correct wordings) and `domain` per term.
- The `sha256` is computed the same way, so a published version cannot be edited quietly: publish a
  new version instead.
- The speech-to-text loader reads this file and ignores the meanings; this loader ignores the
  aliases. One course glossary can later hold both, and a test loads this file with the
  speech-to-text loader to prove it.

**Use** (`ar` and `mixed` modes):
- `prompt_rules(text, mode)` gives the model the meanings of the terms found in the page.
- `wrong_meanings(texts)` checks every «term (Arabic)» and «Arabic (term)» written by the model.
  The comparison ignores diacritics, ال and hamza forms, and accepts `accepted_ar`.
- A mismatch marks the result `needs_review`.
- In `en` mode the glossary is not used.

## Explanation language

`explain.py` (`CB_EXPLAIN_LANGUAGE`, the per-mode instructions and the speech labels) now lives
here. document-reader keeps `reader/explain.py` as a bridge that re-exports it and still raises
its own `ConfigError`, so its behaviour and callers are unchanged. lecture-summarization,
question-generation and the narrator import `cb_shared.explain` directly.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

The tests use a fake Gemini client, so there is no network; a real client is blocked.
