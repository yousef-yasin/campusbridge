# CampusBridge – Arabic Speech-to-Text (STT)

Standalone Python module for Arabic lecture transcription, based on the project document
requirements:

| Requirement (project document) | Implementation |
|---|---|
| Arabic-optimized STT for live and recorded lectures; Whisper or equivalent | `faster-whisper`, language `ar` by default |
| INS-09 start/end live lecture session (status `live` → `ended`) | `LiveSession.start()` / `end()` |
| INS-10 capture instructor microphone and convert to text while speaking | `LiveSession.feed(chunk)`, `record_microphone()`, `on_caption` callback |
| INS-12 associate each text segment with a slide number | `LiveSession.set_slide(n)` → `Segment.slide` |
| INS-13 save the full transcript when the session ends | `LiveSession.end()` saves `.txt` + `.json` |
| Student views full transcript and searches it by keyword | `Transcript.search()`, `stt search` CLI |
| Per audio chunk, STT transcribes and text is appended to the transcript | `Transcriber.transcribe_chunk(audio, offset)` |
| If STT is unavailable, show a notice and continue the lecture without captions | `LiveSession.feed` returns `[]` and sets `last_error`; session stays live |
| TRANSCRIPT entity: `full_text`, `language` | `Transcript.full_text`, `Transcript.language` |

## Layout

```
src/stt/
  config.py       STTConfig (env overrides, CPU/GPU auto-detect)
  transcriber.py  Transcriber: file + chunk transcription
  live.py         LiveSession, record_microphone
  transcript.py   Segment, Transcript (save/load/search)
  errors.py       STTError, AudioNotFoundError, ModelUnavailableError, TranscriptionError
  __main__.py     CLI
tests/            unit tests (fake model) + sample-audio tests (real model)
samples/          place Arabic test audio here
```

## Installation

Python 3.9+.

```bash
cd ai/speech-to-text
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

Models are downloaded from Hugging Face on first use and cached (`medium` ~1.5 GB, `small` ~480 MB).
`faster-whisper` decodes audio via PyAV, so ffmpeg is not required.

## Configuration

Environment variables (CLI `--model` / `--device` override them):

| Variable | Default | Notes |
|---|---|---|
| `STT_MODEL` | `medium` | Saved/uploaded audio (`stt file`, `Transcriber`). `tiny`, `base`, `small`, `medium`, `large-v3`, or a local model path |
| `STT_LIVE_MODEL` | `small` | Live microphone sessions (`stt mic`, `config.for_live()`). Independent of `STT_MODEL` |
| `STT_DEVICE` | `auto` | `cuda` if a CUDA GPU is detected, otherwise `cpu` |
| `STT_COMPUTE_TYPE` | `auto` | `int8` on CPU, `float16` on CUDA |
| `STT_LANGUAGE` | `ar` | |
| `STT_BEAM_SIZE` | `5` | |
| `STT_VAD_FILTER` | `1` | Skip silence (Silero VAD built into faster-whisper) |
| `STT_GLOSSARY` | unset | Path to an approved course glossary; enables technical-term correction (see below). CLI: `--glossary` |

### Model selection

- Saved/uploaded audio uses `medium`. On a single 105 s synthetic Arabic/English TTS clip
  (`samples/bilingual_test.mp3`, CPU int8) it scored 6.8% WER vs 14.6% for `small`, and
  recognised all English technical terms that `small` dropped. It ran at ~0.96× real time
  and ~1.7 GB peak RAM on the development CPU (no NVIDIA GPU).
- Live sessions use `small` (~0.31× real time, ~0.65 GB) so captions keep up on CPU.
- These figures come from one synthetic clip only; real-lecture accuracy has not been measured.
- `--model` on the CLI applies to whichever command is run (file or mic).
- Only one model is kept loaded at a time: Transcribers with the same model share an instance,
  and loading a different model releases the previous one. Alternating between file and live
  transcription in one process therefore reloads the model (a few seconds each switch).

```bash
STT_MODEL=large-v3 python -m stt file lecture.mp3      # override file model
STT_LIVE_MODEL=base python -m stt mic --seconds 60     # override live model
python -m stt --model small file lecture.mp3           # one-off override
```

PowerShell: `$env:STT_MODEL="large-v3"; python -m stt file lecture.mp3`

### Technical-term correction (approved glossary)

Whisper often writes English terms spoken inside Arabic sentences in Arabic script
("الالجوريثم", "الابليمنتيشن"). With an approved course glossary, `src/stt/termfix.py`
rewrites only confidently identified terms. It is deterministic, offline, pure Python, and
never calls a model, an LLM, or the network.

```bash
python -m stt --glossary glossaries/CS301_v3.json file lecture.mp3
```

**Output.** When a glossary is enabled every segment has:
- `raw_text`: the exact recognizer output (including whitespace). It is never modified.
- `text`: `raw_text` with only the Arabic core of matched words replaced.
- `corrections`: always present (`[]` when nothing changed). Each entry has `original`,
  `prefix`, `term`, `replacement`, `kind`, `confidence`, `rule`, `evidence`,
  `char_start`/`char_end` (positions in `raw_text`) and `token_start`/`token_end`.

The transcript JSON also gets `raw_full_text` and `glossary: {course, version, sha256}`.
Timestamps, segment order and slide numbers are never changed. With no glossary configured,
output is byte-identical to before. Keyword search matches both `text` and `raw_text`.

**Matching rules** (only aliases with `status: "approved"` are used):

| Kind | Match | Extra evidence |
|---|---|---|
| `word`, alias ≥ 6 letters | similarity ≥ 0.92 (hamza-alif swap costs 0.5, any other edit 1) | none |
| `word`, alias 4–5 letters | exact | none |
| `phrase` (2–3 words) | exact on every word | none |
| `short` (alias ≤ 3 letters) | exact | **both** E1 and E2 |
| `acronym_letters` (spoken letter by letter, e.g. "اي بي اي") | exact, at least 2 words | **both** E1 and E2 |
| `acronym_word` (spoken as a word, e.g. "سيكول") | exact | **both** E1 and E2 |

- E1: the term is in the current slide's terms (`LiveSession(..., slide_terms={slide: [terms]})`).
- E2: an independently accepted `word`/`phrase` term is within ±3 words in the same segment.
- Evidence never lowers a threshold or raises the confidence score. Slide context alone never
  justifies a correction.
- **Uploaded files have no slide context**, so E1 is never available there. Short terms and
  acronyms in uploaded files are corrected only as part of an approved `phrase` alias.
  Thresholds are not relaxed to recover them.
- If two terms score within 0.05 of each other, or different prefix splits match different
  terms, nothing is changed. `keep_arabic` terms are never replaced. Words in
  `never_correct` are skipped (a secondary safeguard only).
- Comparison removes only diacritics and tatweel. No Arabic letter is mapped to another
  (أ/إ/آ/ا, ة/ه and ى/ي stay distinct).

**Prefixes.** ال، وال، بال، لل، ل، و، ب may be attached to a term (longest first; the
whole word is tried first). A prefix is split off only if the remaining stem (at least 3 letters)
matches an approved alias, and `original == prefix + stem` always holds. The prefix and term
are stored separately. `text` uses this provisional display form, pending team approval: a
joining prefix gets a tatweel, then a space, then the term (`الـ algorithm`, `لـ run experiment`).
A non-joining prefix gets just a space (`و API`). No bidi control characters are stored; RTL
rendering is left to the frontend (for example `<bdi>` around `term`).

**Glossary file.** A glossary is approved and versioned, and must not be edited after use.

```json
{"schema": 1, "course": "CS301", "version": 3, "approved_by": "...", "approved_at": "2026-12-01",
 "terms": [
  {"term": "implementation", "kind": "word",
   "aliases": [{"ar": "ابليمنتيشن", "status": "approved", "source": "rule"},
               {"ar": "امبلمنتيشن", "status": "rejected", "source": "rule"}]},
  {"term": "run experiment", "kind": "phrase", "aliases": [{"ar": "ران اكسبريمنت", "status": "approved"}]},
  {"term": "API", "kind": "acronym_letters", "aliases": [{"ar": "اي بي اي", "status": "approved"}]},
  {"term": "model", "kind": "word", "keep_arabic": true, "aliases": [{"ar": "موديل", "status": "approved"}]}],
 "never_correct": ["بدنا"],
 "sha256": "<sha256 of the canonical JSON without this field>"}
```

`sha256` is computed over `json.dumps(data_without_sha256, sort_keys=True, ensure_ascii=False,
separators=(",", ":"))` (`stt.glossary.compute_sha256` / `seal`). Loading fails if the hash
does not match, so a used version cannot change silently. Publish a new `version` instead.
Saved transcripts keep their recorded glossary version and are never re-corrected implicitly.

The loader also rejects aliases that don't fit their kind. For example, a 3-letter alias must be
`short` and a 1-word alias cannot be `acronym_letters`. It also rejects an approved alias that
belongs to two terms. Building and reviewing glossaries (extracting terms from slides, generating
candidate aliases, instructor approval) is a separate workflow and is not part of this runtime.

**Known, unavoidable risk.** An ordinary Arabic word that is spelled exactly like an approved
alias is corrected when the rules are met. Examples are "كاش" ("cash") for *cache* and "رن"
("rang") for *run*. For short words this needs both slide and adjacent-term evidence, which
reduces but does not remove the risk. The remedy is to reject such aliases during instructor
review. `tests/test_termfix_adversarial.py` documents this case.

**Evaluation and benchmark.**

```bash
python eval/score_terms.py reference.txt hypothesis.json [--glossary approved.json]
python eval/bench_termfix.py [--terms 500] [--segments 2000]
```

`score_terms.py` reports:
- precision (correct ÷ all corrections);
- recall (reference English words gained ÷ those missing from the raw output);
- false corrections per 1,000 Arabic words;
- WER before and after (overall, Arabic, English);
- optionally, the latency of re-running correction.

Use only recordings with human-corrected transcripts that were **not** used to write aliases or
tune thresholds.

Benchmark on the development CPU (synthetic glossary and text, so this measures speed only, not
accuracy):

| Glossary | Live 5 s chunk (~10 words) p50 / p95 | File segment (~40 words) p50 / p95 | Build |
|---|---|---|---|
| 500 terms / 900 aliases | 0.38 / 0.82 ms | 1.63 / 3.27 ms | 39 ms, 0.6 MiB |
| 2000 terms / 3600 aliases | 0.64 / 1.14 ms | 2.88 / 7.46 ms | 218 ms, 2.4 MiB |

## Usage

CLI (run from `ai/speech-to-text`, with `src` on the path):

```bash
# Windows PowerShell: $env:PYTHONPATH="src"     bash: export PYTHONPATH=src
python -m stt file samples/lecture.wav -o transcripts/lecture.txt
python -m stt mic --seconds 300 --chunk 5 -o transcripts/live.txt
python -m stt search transcripts/lecture.json "الخوارزمية"
python -m stt --model medium file samples/lecture.mp3
```

Output: `<name>.txt` (UTF-8, one `[HH:MM:SS - HH:MM:SS] [slide N] text` line per segment) and
`<name>.json` (`language`, `full_text`, `segments` with `start`, `end`, `text`, `slide`).

Python API (for future backend/API integration):

```python
from stt import Transcriber, LiveSession, STTConfig

cfg = STTConfig.from_env()                 # model=medium, live_model=small unless overridden
transcript = Transcriber(cfg).transcribe_file("lecture.wav")
transcript.save("lecture.txt")
transcript.search("مقدمة")

live = Transcriber(cfg.for_live())         # uses live_model
session = LiveSession(live, "live.txt", on_caption=lambda seg: print(seg.text))
session.start()
session.set_slide(1)
session.feed(pcm_float32_16khz_mono)   # call per audio chunk
transcript = session.end()             # saves live.txt / live.json
```

## Tests

```bash
cd ai/speech-to-text
python -m pytest -q
```

Unit tests use a fake model (no download). `tests/test_samples.py` runs the real model on audio in
`samples/` and is skipped when that folder has no audio. It only checks that Arabic text with valid
timestamps is produced; it does not measure accuracy.

## Limitations

- No Arabic or Jordanian lecture recordings were available, so Arabic/Jordanian-dialect accuracy
  has **not** been measured. Add samples with reference transcripts and evaluate before relying on it.
- Live mode transcribes fixed-length chunks independently; words cut at chunk boundaries may be
  lost or split, and captions lag by roughly the chunk length plus processing time.
- On CPU, `medium`/`large-v3` are too slow for live captions; keep `STT_LIVE_MODEL` at `small`
  unless a GPU is available (GPU speed not measured).
- `Transcriber()` with no arguments now defaults to `medium` (previously `small`); pass
  `STTConfig(model="small")` or set `STT_MODEL=small` for the old behaviour.
- Keyword search normalizes diacritics and alef forms only; it is substring-based, not semantic.
- Term correction never crosses segment boundaries. In live mode, a multi-word term split
  across two 5 s chunks (for example "ران" at the end of one chunk and "اكسبريمنت" at the start
  of the next) is not corrected.
- Term-correction accuracy has not been measured on real lectures. No human-corrected
  evaluation recordings exist yet.
- Correction only handles spellings that are in the approved glossary. Whisper spellings outside
  alias reach (for example "الجرثن") stay unchanged.
- The CLI `mic` command has no slide context, so short terms and acronyms there are corrected
  only inside approved phrases.
- No HTTP API, authentication, or database persistence (left to backend integration).
- Transcript retention/deletion policy is handled outside this module.
