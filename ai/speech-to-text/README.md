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

The model is downloaded from Hugging Face on first use (~480 MB for `small`) and cached.
`faster-whisper` decodes audio via PyAV, so ffmpeg is not required.

## Configuration

Environment variables (CLI `--model` / `--device` override them):

| Variable | Default | Notes |
|---|---|---|
| `STT_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, or a local model path |
| `STT_DEVICE` | `auto` | `cuda` if a CUDA GPU is detected, otherwise `cpu` |
| `STT_COMPUTE_TYPE` | `auto` | `int8` on CPU, `float16` on CUDA |
| `STT_LANGUAGE` | `ar` | |
| `STT_BEAM_SIZE` | `5` | |
| `STT_VAD_FILTER` | `1` | Skip silence (Silero VAD built into faster-whisper) |

Default `small` was chosen because the development machine has no NVIDIA GPU (CPU, 16 threads).
For better Arabic quality use `medium` or `large-v3`, preferably on a GPU.

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

tr = Transcriber(STTConfig(model="small"))
transcript = tr.transcribe_file("lecture.wav")
transcript.save("lecture.txt")
transcript.search("مقدمة")

session = LiveSession(tr, "live.txt", on_caption=lambda seg: print(seg.text))
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
- On CPU, `medium`/`large-v3` may be too slow for live captions.
- Keyword search normalizes diacritics and alef forms only; it is substring-based, not semantic.
- No HTTP API, authentication, or database persistence (left to backend integration).
- Transcript retention/deletion policy is handled outside this module.
