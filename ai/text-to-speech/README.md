# CampusBridge – Arabic/English Text-to-Speech (TTS)

Standalone Python module that reads Arabic and English text aloud into an audio file. It follows
the same layout and conventions as `ai/speech-to-text`.

> **Where the text goes.** With the default engine (`gemini`) every text is **sent to Google's
> servers**. On the free tier Google states the content is **used to improve its products**
> (pricing page, "Used to improve our products: Yes"; "No" on the paid tier). The first fallback
> (`edge`) sends the text to Microsoft through `edge-tts`, an **unofficial** client of the Edge
> "Read aloud" service with no service guarantee. Only `TTS_ENGINE=piper` keeps everything on
> this machine. Do not send private or sensitive text through the online engines.

| Requirement | Implementation |
|---|---|
| Turn Arabic/English text into an audio file | `Synthesizer.synthesize(text, out)`, `tts say` |
| Three engines behind one interface, switchable from settings; Gemini TTS is the default | `Engine`, `GeminiEngine`, `EdgeEngine`, `PiperEngine`, `TTS_ENGINE` / `--engine` |
| Gemini model configurable (`gemini-3.8-flash-tts` default, `gemini-3.8-flash-lite-tts`) | `TTS_GEMINI_MODEL` / `--model` |
| Single-speaker voice: Nika (default female), Finn (default male), in the voice list | `voices.PRESET_VOICES`, `TTS_GEMINI_VOICE` / `--voice`, `tts voices` |
| Editable style instructions with a lecturer default | `TTS_GEMINI_STYLE` / `--style` (sent as `speech_metadata.style`) |
| Gemini gets the raw text: no language split, no number expansion; long text split at paragraph breaks only | `text.split_paragraphs()`, `TTS_GEMINI_MAX_CHARS` |
| API key read from `GEMINI_API_KEY` in `.env`, never printed or logged | `keys.py` (`get_key`, `scrub`) |
| Fallback chain Gemini → edge-tts (`ar-JO-SanaNeural`) → Piper; quota (429), missing key and no internet all trigger it, with the reason recorded | `Synthesizer.fallbacks`, `Synthesizer.fallback_reasons`, warning log |
| Cache covers engine, model, voice and style | `AudioCache.key(..., extra)` |
| Language detection, mixed-text split and number expansion (edge and Piper) | `text.prepare()` |
| Adjustable speed | `TTS_SPEED` / `--speed` (0.5 – 2.0) |
| Default quick phrases plus add / edit / remove custom phrases | `PhraseBook`, `tts phrases` |
| Failure returns a clear error and does not stop the program | `TTSError` subclasses, `try_synthesize()` / `last_error`, CLI exit code 1 |

## Layout

```
src/tts/
  config.py       TTSConfig (env overrides, validation)
  keys.py         API key lookup (.env / environment), scrubbing of secrets
  voices.py       PRESET_VOICES per engine, aliases, fallback voice
  text.py         raw paragraph split (Gemini); clean, sentences, language, numbers (edge, Piper)
  engines.py      Engine interface, GeminiEngine, EdgeEngine, PiperEngine, get_engine
  synthesizer.py  Synthesizer: text / file -> one audio file, fallback chain
  cache.py        AudioCache
  phrases.py      PhraseBook (default + custom quick phrases)
  errors.py       TTSError and subclasses
  __main__.py     CLI
tests/            unit tests (fake engines, no network, no real key) + real-engine tests
.env              GEMINI_API_KEY (not in git)        .env.example  template (in git)
voices/           Piper voice models (not in git)
.tts-cache/       cached audio clips (not in git)
data/phrases.json custom quick phrases (not in git)
samples-out/      listening samples (not in git)
```

## Installation

Python 3.12 (developed and tested on 3.12.10, Windows).

```bash
cd ai/text-to-speech
py -3.12 -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

**API key.** Copy `.env.example` to `.env` and put a Gemini API key from Google AI Studio
(<https://aistudio.google.com/apikey>) after `GEMINI_API_KEY=`. `.env` is ignored by git. A
`GEMINI_API_KEY` environment variable takes priority over the file. Without a key the module
still works: every request falls back to edge-tts and says so.

**Piper voices** for the offline fallback (about 126 MB, from Hugging Face):

```bash
python -m piper.download_voices ar_JO-kareem-medium en_US-lessac-medium --data-dir voices
```

## Engines

| | `gemini` (default) | `edge` | `piper` |
|---|---|---|---|
| Runs | Google servers | Microsoft servers (unofficial client) | this machine |
| Needs | `GEMINI_API_KEY`, internet | internet | voice models in `voices/` |
| Output | `.wav` (24 kHz mono 16-bit) | `.mp3` | `.wav` |
| Mixed Arabic/English | one voice, raw text | one Multilingual voice, or one voice per language | one voice per language |
| Numbers | read by the model | expanded to words per sentence language | expanded to words per sentence language |
| Speed | approximate (style: `speaking slowly` / `speaking rapidly`) | exact percent | exact |

### Gemini TTS

- **Model**: `gemini-3.8-flash-tts` by default. `TTS_GEMINI_MODEL=gemini-3.8-flash-lite-tts` (or
  `--model`) switches to the cheaper, faster model; Google says both share the same API schema.
  The client uses the `v1beta` API, which these models require.
- **Voices**: `Nika` (default, female) and `Finn` (male). `--voice` accepts `nika`, `finn`,
  `female`, `male`, or any other Gemini voice name. Nika and Finn are not among the 30 prebuilt
  voices listed in Google's guide; they come from the Extended Voice Library and were verified
  by real requests (see "Tests").
- **Style**: sent in `speech_metadata.style`, separate from the transcript, so it is not read
  aloud. Default:
  `friendly university lecturer, clear Arabic, English terms and sentences in natural English pronunciation`.
  Change it with `TTS_GEMINI_STYLE` / `--style`; an empty value sends no style. Google's guide
  recommends short style strings and warns that long instructions, and instructions to "keep
  the same voice", increase voice drift, so the default does not say "same voice": the single
  configured voice already guarantees one speaker.
- **Raw text**: the text is sent exactly as written. No sentence splitting, no language split,
  no number expansion; `--lang` has no effect on Gemini.
- **Long text**: text up to `TTS_GEMINI_MAX_CHARS` (default 3000) is one request. Longer text is
  split **only at paragraph breaks** (blank lines; single line breaks if there are none) and
  the parts are joined into one WAV. A single paragraph longer than the limit is sent whole.
  The 3000 default is our own conservative choice under the model's documented limits (input
  8,192 tokens, output 16,384 tokens, 25 audio tokens per second ≈ 10.9 minutes of audio per
  request); it has not been tuned against real long lectures.
- **Speed**: Gemini has no numeric speed. `--speed` below 0.9 adds `speaking slowly` to the
  style and above 1.1 adds `speaking rapidly`; values in between change nothing.

### Free tier limits (checked against Google's documentation on 2026-11-17)

| Fact | Source |
|---|---|
| `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts` both have a free tier: input and output "Free of charge" | Pricing page |
| Free-tier content is "Used to improve our products: Yes"; paid tier: "No" | Pricing page |
| Paid price for `gemini-3.8-flash-tts`: $0.50 / 1M input tokens, $9.00 / 1M audio output tokens (≈ $0.00225 per 10 s) through 2026-12-31, doubling on 2027-01-01. Flash-Lite: $0.50 and $6.00 | Pricing page |
| Limits are measured as requests per minute (RPM), input tokens per minute (TPM) and requests per day (RPD); they apply **per project, not per API key**; RPD resets at midnight Pacific time | Rate limits page |
| Exceeding a limit returns `429 RESOURCE_EXHAUSTED` | Rate limits page |
| **The exact free-tier RPM / TPM / RPD numbers for the TTS models are not published in the docs.** The page says limits "can be viewed in Google AI Studio" and are "not guaranteed" | Rate limits page |
| Per request: 8,192 input tokens, 16,384 output tokens | Model page |

So the numbers for your project must be read on the rate limits page inside Google AI Studio
while signed in (linked from the rate limits doc); we could not verify them from here.
The audio cache reduces quota use (the same text, voice, model and style is never requested
twice), and a 429 falls back to edge-tts automatically.

Sources: <https://ai.google.dev/gemini-api/docs/speech-generation>,
<https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts>,
<https://ai.google.dev/gemini-api/docs/rate-limits>, <https://ai.google.dev/gemini-api/docs/pricing>.

### edge-tts

`edge-tts` is an unofficial client of the Microsoft Edge "Read aloud" service: no contract, no
quota guarantee, and it may change or stop without notice. Presets (all Multilingual: one voice
reads the whole text): `william` (`en-AU-WilliamMultilingualNeural`, default male), `emma`
(`en-US-EmmaMultilingualNeural`, default female), `brian`, `remy`, `vivienne`. A single-language
voice name (for example `ar-JO-TaimNeural`) or an empty `TTS_EDGE_VOICE` switches to one voice
per language (`TTS_EDGE_VOICE_AR` / `TTS_EDGE_VOICE_EN`).

### Piper

Local. The Piper index has one Arabic voice, `ar_JO-kareem` (`low` / `medium`). Defaults:
`ar_JO-kareem-medium` and `en_US-lessac-medium`. Mixed text is always split by language.

## Fallback chain

With `TTS_FALLBACK` on (default):

| Engine that failed | Next |
|---|---|
| `gemini`: no API key, key rejected, quota / rate limit (429), no internet, service error, no audio | `edge` with `ar-JO-SanaNeural` reading the whole text |
| `edge`: chosen voice returned no audio | `edge` with `ar-JO-SanaNeural` |
| `edge`: unreachable (no internet), or the fallback voice failed too | `piper` |
| `piper` | nothing: one `TTSError` listing every failure; no file is written |

Every step is logged as a warning with its reason
(`TTS fallback -> edge:ar-JO-SanaNeural (reason: Gemini quota or rate limit exceeded (429): ...)`).
After a call, `Synthesizer.fallbacks` holds what was used (`["edge:ar-JO-SanaNeural"]` or
`["piper"]`) and `Synthesizer.fallback_reasons` the errors; the CLI prints
`Fallback used: ... (reason: ...)`. The output extension follows the engine that produced the
audio (`.wav` for Gemini and Piper, `.mp3` for edge), so always use the returned path.

A fallback engine prepares the text its own way: edge and Piper expand numbers to words and
(Piper) split by language, unlike Gemini. `--no-fallback` / `TTS_FALLBACK=0` turns the chain off.

## Configuration

Environment variables (CLI `--engine` / `--voice` / `--model` / `--style` / `--lang` / `--speed` /
`--no-cache` / `--no-fallback` override them):

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | (none) | In `.env` or the environment. Secret; never logged |
| `TTS_ENGINE` | `gemini` | `gemini`, `edge` or `piper` |
| `TTS_GEMINI_MODEL` | `gemini-3.8-flash-tts` | Or `gemini-3.8-flash-lite-tts` |
| `TTS_GEMINI_VOICE` | `Nika` | Alias, `male`, `female` or any Gemini voice name |
| `TTS_GEMINI_STYLE` | lecturer style above | Empty = no style |
| `TTS_GEMINI_MAX_CHARS` | `3000` | Longer text is split at paragraph breaks |
| `TTS_GEMINI_TIMEOUT` | `180` | Seconds per request |
| `TTS_ENV_FILE` | `.env` in this module | File that holds `GEMINI_API_KEY` |
| `TTS_FALLBACK` | `1` | `0` disables the fallback chain |
| `TTS_EDGE_FALLBACK_VOICE` | `ar-JO-SanaNeural` | edge voice used by the chain |
| `TTS_EDGE_VOICE` | `en-AU-WilliamMultilingualNeural` | When the engine is `edge` |
| `TTS_EDGE_VOICE_AR` / `_EN` | `ar-JO-SanaNeural` / `en-US-AriaNeural` | edge without a Multilingual voice |
| `TTS_PIPER_VOICE_AR` / `_EN` | `ar_JO-kareem-medium` / `en_US-lessac-medium` | |
| `TTS_VOICES_DIR` | `voices/` in this module | Piper models |
| `TTS_LANGUAGE` | `auto` | `auto`, `ar`, `en` (edge and Piper only) |
| `TTS_FALLBACK_LANGUAGE` | `ar` | `auto` mode: sentence with no words, or a tie |
| `TTS_SPEED` | `1.0` | 0.5 to 2.0 |
| `TTS_CACHE` / `TTS_CACHE_DIR` | `1` / `.tts-cache/` | |
| `TTS_PHRASES_FILE` | `data/phrases.json` | Custom quick phrases |
| `TTS_MAX_CHARS` | `250` | Sentence length limit (edge and Piper) |
| `TTS_TIMEOUT` | `30` | edge-tts network timeout in seconds |

## Usage

CLI (run from `ai/text-to-speech`, with `src` on the path):

```bash
# Windows PowerShell: $env:PYTHONPATH="src"     bash: export PYTHONPATH=src
python -m tts voices                                   # ready-made voices of all engines
python -m tts say "مرحباً بكم في المحاضرة 7" -o out/hello          # Gemini, Nika -> hello.wav
python -m tts --voice finn file notes.txt              # -> notes.wav
python -m tts --model gemini-3.8-flash-lite-tts --style "calm narrator" say "Welcome"
python -m tts --engine edge --voice emma say "Thank you" -o out/thanks   # -> thanks.mp3
python -m tts --engine piper say "Thank you" -o out/local                # offline

python -m tts phrases                                  # list (id <tab> text)
python -m tts phrases add "أين القاعة؟"                # -> c1
python -m tts phrases edit c1 "أين قاعة 204؟"
python -m tts phrases say c1 -o out/c1
python -m tts phrases remove c1
```

On error the CLI prints `Error: ...` and exits with code 1.

Python API (for future backend/API integration):

```python
from tts import Synthesizer, TTSConfig, PhraseBook, TTSError

cfg = TTSConfig.from_env()             # gemini + Nika unless overridden
cfg.set_voice("finn")                  # voice of the selected engine
tts = Synthesizer(cfg)
path = tts.synthesize("أهلاً بكم في المحاضرة 7. Welcome.", "out/welcome")   # TTSError on failure
if tts.fallbacks:                      # e.g. ["edge:ar-JO-SanaNeural"]: path is then .mp3
    print("fallback:", tts.fallbacks, tts.fallback_reasons[0])

path = tts.try_synthesize("نص")        # never raises: None + tts.last_error on failure

book = PhraseBook(cfg.phrases_file)
phrase = book.add("أين القاعة؟")       # book.update(id, text), book.remove(id), book.list()
tts.synthesize(phrase.text, f"out/{phrase.id}")
```

Errors (all subclasses of `TTSError`): `ConfigError`, `EmptyTextError`, `InputNotFoundError`,
`EngineUnavailableError` (and its subclass `QuotaExceededError` for 429), `VoiceNotFoundError`,
`SynthesisError`, `PhraseError`.

## Pronunciation dictionary

`pronunciation.json` (committed, in this folder) lists words with their correct diacritics:
Jordanian places (الرصيفة → الرُّصَيْفَة, الحسا, الشيدية, صويلح, ناعور, الأزرق, الريشة,
وادي عربة, ضانا, ...) and scientific terms (المغنيسيوم, البوتاسيوم, المنغنيز, اليورانيوم,
...).

How it is applied:
- It runs on the text right before it is sent to any engine (Gemini, Edge or Piper). It changes
  only what is spoken; the text the caller passed, and what the app shows, stay as written.
- It matches whole words, alone or with the prefixes و ف ب ك ل, and للـ for words starting with
  ال (للرصيفة).
- Words already written with diacritics are left alone.
- Spoken segments are cached by their spoken text, so a new entry gives new audio.

Adding words:
- Edit the JSON (any group, or a new group), or use the API:

  ```python
  from tts import Pronunciations
  book = Pronunciations("pronunciation.json")
  book.add("الطفيلة", "الطَّفِيلَة")            # group "custom" unless given; the file is saved
  book.apply("في الطفيلة")                     # -> "في الطَّفِيلَة"
  ```
- The spoken form must be the same word with diacritics only. `add` refuses anything else, and a
  test checks the whole file.
- Leave out words whose vocalization depends on meaning, such as عمان (Amman or Oman) and معان
  (the city, or "meanings").

Settings: `TTS_PRONUNCIATION_FILE` points to another file, and `TTS_PRONUNCIATION=0` turns the
dictionary off.

## API key safety

- The key lives only in `.env` (git-ignored) or the process environment. It is read at request
  time and is not a field of `TTSConfig`, so it cannot appear in a printed config.
- Error messages pass through `keys.scrub()`, which replaces the key with `***`, and Gemini
  errors are raised without their original cause attached.
- The key is sent to Google in a request header, not in the URL.
- The CLI prints an `HTTP Request: POST https://generativelanguage.googleapis.com/...` line for
  each Gemini call (from the HTTP library); it contains the model name, not the key.

## Tests

```bash
cd ai/text-to-speech
python -m pytest -q
```

Unit tests use fake engines and a fake Gemini client; the real Gemini and edge clients are
blocked and the real `.env` is not read, so they need no key and no network.
`tests/test_real_engines.py` is skipped by default: Piper runs once both voices are in
`voices/`; `TTS_TEST_EDGE=1` calls edge-tts; `TTS_TEST_GEMINI=1` calls the Gemini API with the
key in `.env` (uses quota, sends text to Google). They only check that playable audio is
produced, not pronunciation.

## Limitations

- **Privacy**: see the note at the top. The default engine sends text to Google, and on the free
  tier that content may be used to improve Google's products.
- **Free-tier limits are unknown to this module** (not published; see above). A class reading
  many texts in a short time can hit 429; requests then fall back to edge-tts, which changes the
  voice (Nika/Finn → Sana) and the file format (`.wav` → `.mp3`).
- A 429 is not retried and the module does not wait for the quota to reset.
- Gemini audio quality, Arabic pronunciation and the handling of English terms were judged only
  on short samples; nothing has been evaluated on real lectures. Output is not deterministic:
  the same text can sound slightly different on a new request (the cache hides this).
- `--speed` is approximate on Gemini (three steps), and `--lang` is ignored there.
- Text over `TTS_GEMINI_MAX_CHARS` without paragraph breaks is sent as one request and may be
  rejected by the API; the joined parts of a long text are separate generations and may differ
  slightly in tone.
- Voice names are not validated: an unknown Gemini voice fails at request time and falls back.
- edge-tts is unofficial and can stop working. Its fallback detects "no audio" and connection
  errors only, not mispronounced or skipped words.
- Piper has a single Arabic speaker and relies on automatic diacritization.
- Number expansion (edge and Piper only) ignores Arabic gender/case agreement; dates, times,
  currencies, negatives, ordinals and units are not expanded. Sentence splitting is
  punctuation-based.
- The cache has no size limit or expiry; clear it by deleting `.tts-cache/`.
- No audio playback, streaming, HTTP API, authentication or database persistence (see
  `docs/api-contracts/text-to-speech.md` for the draft contract).
