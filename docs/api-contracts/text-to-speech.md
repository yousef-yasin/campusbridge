# Text-to-Speech API Contract (DRAFT)

**Status: draft, not agreed and not implemented.** This is a proposal from the AI team for
review by the Web team. Today the module (`ai/text-to-speech`) is a Python library and CLI only;
no HTTP service exists yet. Paths, field names and limits below are open for discussion.

## Important: text leaves the server by default

| Engine | Where the text goes | Status |
|---|---|---|
| `gemini` (default) | Google (Gemini API). On the free tier Google states content is "Used to improve our products"; not on the paid tier | Official API, needs an API key and has quotas |
| `edge` (first fallback) | Microsoft, through `edge-tts` | **Unofficial** client of the Edge "Read aloud" service: no SLA, no documented quota, may stop without notice |
| `piper` (last fallback) | Stays on the server | Local models |

Consequences for the contract:

- Private or sensitive content must be sent with `engine: "piper"`, or the server must be
  configured for Piper only.
- TTS must be treated as optional by the Web side: quotas and outages are expected.
- A response can come from a different engine, voice and audio format than requested (see
  "Fallback").

Open questions for both teams: is the Gemini free tier (content used by Google, unpublished
rate limits) acceptable for student lecture text, or does the project need the paid tier? Is an
unofficial service acceptable as a fallback in production?

## Overview

The AI service turns Arabic/English text into an audio file and manages a student's quick
phrases. The backend (ASP.NET Core) calls it; the browser never calls it directly.

- Base path: `/api/ai/tts`
- Request and response bodies: JSON, UTF-8
- Authentication, per-user authorization and rate limiting: handled by the backend (to be agreed)
- The Gemini API key is server configuration (`GEMINI_API_KEY`). It never appears in requests,
  responses, error messages or logs.

## POST `/api/ai/tts/synthesize`

Convert text to speech.

Request:

```json
{
  "text": "أهلاً بكم في المحاضرة 7. اليوم سنتحدث عن machine learning.",
  "voice": "nika",
  "speed": 1.0,
  "engine": "gemini",
  "style": null,
  "language": "auto"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `text` | string | yes | Proposed limit: 3,000 characters per request (the module's Gemini request size). Longer text: the module splits at paragraph breaks only |
| `voice` | string | no | A voice `alias` or `name` from `GET /voices` for the chosen engine, or `male` / `female`. Default: `nika`. Ignored by `piper` |
| `speed` | number | no | 0.5 to 2.0, default 1.0. Approximate on `gemini` (slow / normal / fast); exact on `edge` and `piper` |
| `engine` | string | no | `gemini` (default), `edge`, `piper` |
| `style` | string | no | Gemini only. Delivery instructions; default is a friendly university lecturer style. Proposed: server configuration only, not settable by clients |
| `language` | string | no | `auto` (default), `ar`, `en`. Used by `edge` and `piper` for reading numbers; ignored by `gemini`, which reads the raw text |

How the text is read:

- `gemini`: the text is sent as written; one voice reads Arabic and English, and the model reads
  numbers itself.
- `edge` / `piper`: numbers are expanded to words in the language of their sentence. `piper`
  (and `edge` without a Multilingual voice) splits mixed text and uses one voice per language.

Response `200 OK`: the audio file itself.

| Header | Values | Notes |
|---|---|---|
| `Content-Type` | `audio/wav` (gemini, piper) or `audio/mpeg` (edge) | **Follows the engine that produced the audio.** A Gemini request answered by the edge fallback returns `audio/mpeg`. Clients must read this header |
| `X-TTS-Engine` | `gemini`, `edge`, `piper` | Engine that produced the audio |
| `X-TTS-Voice` | e.g. `Nika`, `ar-JO-SanaNeural` | Voice that produced the audio (not set for piper) |
| `X-TTS-Fallback` | absent, `edge:ar-JO-SanaNeural`, `piper` | Present only when a fallback was used |
| `X-TTS-Fallback-Reason` | e.g. `quota`, `no_api_key`, `unreachable`, `no_audio` | Proposed short code; the module currently exposes the full error text in `Synthesizer.fallback_reasons` |
| `X-TTS-Cache` | `hit`, `miss` | Proposed; the module does not report this yet |

Gemini audio is WAV, 24 kHz, mono, 16-bit (about 2.9 MB per minute). Open question: convert to a
compressed format on the server before sending to browsers.

Open question: return the audio bytes directly (above) or a JSON body with a URL to a stored
file (`{"audio_url": "...", "format": "wav", "engine": "gemini", "fallback": null}`).

## Fallback

| Engine that failed | Next |
|---|---|
| `gemini`: no API key, key rejected, quota or rate limit (HTTP 429 from Google), no internet, service error, no audio | `edge` with `ar-JO-SanaNeural` |
| `edge`: voice returned no audio | `edge` with `ar-JO-SanaNeural` |
| `edge`: unreachable, or the fallback voice failed too | `piper` |
| `piper` | error response |

The response is still `200 OK` when a fallback succeeded; `X-TTS-Fallback` says which one. The
service logs every fallback with its reason. A Google 429 is therefore **not** passed to the
client as 429 unless every fallback also fails or `engine` fallbacks are disabled on the server.

Open question: should the UI tell the student that a different voice is being used?

## GET `/api/ai/tts/voices`

Voices the user can choose from.

```json
{
  "engine": "gemini",
  "default": "Nika",
  "fallback": "ar-JO-SanaNeural",
  "voices": [
    {"engine": "gemini", "alias": "nika", "name": "Nika", "gender": "female", "default": true},
    {"engine": "gemini", "alias": "finn", "name": "Finn", "gender": "male", "default": true},
    {"engine": "edge", "alias": "william", "name": "en-AU-WilliamMultilingualNeural", "gender": "male", "default": true},
    {"engine": "edge", "alias": "emma", "name": "en-US-EmmaMultilingualNeural", "gender": "female", "default": true},
    {"engine": "edge", "alias": "brian", "name": "en-US-BrianMultilingualNeural", "gender": "male", "default": false},
    {"engine": "edge", "alias": "remy", "name": "fr-FR-RemyMultilingualNeural", "gender": "male", "default": false},
    {"engine": "edge", "alias": "vivienne", "name": "fr-FR-VivienneMultilingualNeural", "gender": "female", "default": false}
  ]
}
```

`default: true` marks the default voice of each gender within its engine; the top-level `default`
is used when the request has no `voice`. Open question: store the student's chosen voice in the
backend user profile and send it with each request.

## Quick phrases

Default phrases are the same for everyone and read-only (ids `d1`, `d2`, ...). Custom phrases
(ids `c1`, `c2`, ...) can be added, edited and removed.

Open question: the module stores custom phrases in one JSON file. Per-student phrases need
storage in the backend database, keyed by user; the backend would then own these endpoints and
call only `/synthesize`.

### GET `/api/ai/tts/phrases`

```json
{
  "phrases": [
    {"id": "d1", "text": "مرحباً", "custom": false},
    {"id": "c1", "text": "أين القاعة؟", "custom": true}
  ]
}
```

### POST `/api/ai/tts/phrases`

Request `{"text": "أين القاعة؟"}` → `201 Created` with `{"id": "c1", "text": "أين القاعة؟", "custom": true}`.

### PUT `/api/ai/tts/phrases/{id}`

Request `{"text": "أين قاعة 204؟"}` → `200 OK` with the updated phrase.

### DELETE `/api/ai/tts/phrases/{id}`

→ `204 No Content`.

### POST `/api/ai/tts/phrases/{id}/speak`

Optional body `{"voice": "finn", "speed": 1.0}` → same response as `/synthesize`. Quick phrases
are short and repeated, so they are served from the cache after the first request.

## Errors

All errors use one JSON shape. The service keeps running after any of them. Messages never
contain the API key.

```json
{"error": {"code": "engine_unavailable", "message": "All engines failed. Gemini quota or rate limit exceeded (429): ... | edge:ar-JO-SanaNeural: edge-tts service unreachable ... | piper: Piper voice 'ar_JO-kareem-medium' not found"}}
```

| HTTP | `code` | Module error | When |
|---|---|---|---|
| 400 | `invalid_config` | `ConfigError` | Unknown engine or language, speed out of range |
| 400 | `empty_text` | `EmptyTextError` | Text is empty or has nothing speakable |
| 400 | `invalid_phrase` | `PhraseError` | Empty phrase text, or editing/removing a default phrase |
| 404 | `phrase_not_found` | `PhraseError` | Unknown phrase id |
| 413 | `text_too_long` | (new) | Text over the agreed limit |
| 429 | `quota_exceeded` | `QuotaExceededError` | Gemini quota hit and fallbacks are disabled or all failed |
| 502 | `synthesis_failed` | `SynthesisError` | The engine returned no audio and every fallback failed too |
| 503 | `engine_unavailable` | `EngineUnavailableError` | No API key or no internet, and every fallback failed too |
| 503 | `voice_not_found` | `VoiceNotFoundError` | `engine: "piper"` requested and the voice model is missing on the server |

Notes:

- The module currently raises `PhraseError` for both the 400 and 404 phrase cases; the HTTP
  layer would need to tell them apart.
- An unknown `voice` name is not validated by the module: the engine fails and the request falls
  back to `ar-JO-SanaNeural`. The HTTP layer should reject names that are not in `GET /voices`
  with `400 invalid_config`.

When TTS is unavailable the client should show the text without audio and continue.

## Quotas and cost (Gemini)

- Both `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts` have a free tier. Google does not
  publish the free-tier requests-per-minute / per-day numbers for these models in its docs; they
  are shown per project in Google AI Studio. Limits apply per project, not per API key, so all
  students share one quota.
- Paid tier for `gemini-3.8-flash-tts`: $0.50 per 1M input tokens and $9.00 per 1M audio output
  tokens (about $0.00225 per 10 seconds of audio) through 2026-12-31, doubling from 2027-01-01.
- Per request: 8,192 input tokens, 16,384 output tokens (about 10.9 minutes of audio).
- The service caches audio by engine + model + voice + style + speed + text, so a repeated text
  costs no quota.

Open question: the backend should rate-limit per student so one user cannot use up the shared
quota.

## Not covered yet

- Streaming audio while it is generated (Gemini supports streaming; the module does not use it)
- Word/sentence timing for highlighting text during playback
- Cache retention and deletion policy
- Retrying after a 429 instead of falling back
