"""Vision engine: Gemini (Google). Images and their context are sent to Google's servers.

The API key is read from GEMINI_API_KEY (process environment, else config.env_file) at request
time and is never stored, logged or printed.
"""
import json
import re
import time
from typing import Any, Dict

from .config import ReaderConfig
from .errors import ReaderError, VisionBusyError, VisionError, VisionQuotaError, VisionUnavailableError
from .keys import get_key, scrub


class GeminiVision:
    """describe(image, mime, prompt, schema) -> dict parsed from the model's JSON answer."""
    name = "gemini"

    def __init__(self, config: ReaderConfig, client=None):
        self.config = config
        self.model = config.vision_model.strip()
        self._client = client            # injected client (tests)

    def _get_client(self, key: str):
        if self._client is not None:
            return self._client
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise VisionUnavailableError(
                f"google-genai is not installed (pip install google-genai): {exc}") from exc
        if not key:
            raise VisionUnavailableError(f"GEMINI_API_KEY is not set (put it in {self.config.env_file})")
        return genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=self.config.vision_timeout * 1000))

    # Server errors (500/503 "high demand") are retried after these pauses. The last attempt asks
    # for plain JSON without the schema: schema-constrained requests failed more often with 503
    # in testing (2026-11-18), and the prompt already lists every field.
    retry_pauses = (5.0, 10.0)

    def describe(self, image: bytes, mime: str, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        key = get_key("GEMINI_API_KEY", self.config.env_file)
        client = self._get_client(key)
        attempts = [schema] * len(self.retry_pauses) + [None]
        for number, attempt_schema in enumerate(attempts):
            try:
                text = self._request(client, image, mime, prompt, attempt_schema)
                break
            except ReaderError:
                raise
            except Exception as exc:
                error = self._error(exc, key)                  # the cause may hold request details
                busy = getattr(exc, "code", None) in (500, 503)
                if not busy or number == len(attempts) - 1:
                    raise error from None
                time.sleep(self.retry_pauses[min(number, len(self.retry_pauses) - 1)])
        try:
            data = json.loads(text)
        except ValueError:
            raise VisionError(f"vision model returned no valid JSON: {text[:120]!r}") from None
        if isinstance(data, list):              # a bare array answers the schema's first array field
            field = next((k for k in schema.get("required", [])
                          if (schema.get("properties", {}).get(k) or {}).get("type") == "array"), None)
            data = {field: data} if field else data
        if not isinstance(data, dict):
            raise VisionError("vision model returned JSON that is not an object")
        missing = [f for f in schema.get("required", []) if f not in data]
        if missing:
            raise VisionError(f"vision model answer is missing {', '.join(missing)}")
        return data

    def _request(self, client, image, mime, prompt, schema) -> str:
        from google.genai import types
        settings = {"response_mime_type": "application/json", "temperature": 0.2}
        if schema:
            settings["response_json_schema"] = schema
        if self.config.vision_thinking:
            settings["thinking_config"] = types.ThinkingConfig(thinking_level=self.config.vision_thinking)
        response = client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=image, mime_type=mime)],
            config=types.GenerateContentConfig(**settings))
        return response.text or ""

    def _error(self, exc: Exception, key: str) -> VisionError:
        code = getattr(exc, "code", None)
        detail = scrub(f"{type(exc).__name__}: {getattr(exc, 'message', None) or exc}", key)[:300]
        if code == 429:
            match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(getattr(exc, "details", "")))
            return VisionQuotaError(f"Gemini quota or rate limit exceeded (429): {detail}",
                                    float(match.group(1)) if match else 0.0)
        if code in (401, 403):
            return VisionUnavailableError(f"Gemini rejected the API key ({code}): {detail}")
        module = type(exc).__module__
        if isinstance(exc, (OSError, TimeoutError)) or module.startswith(("httpx", "httpcore", "aiohttp")):
            return VisionUnavailableError(f"Gemini unreachable (internet required): {detail}")
        if isinstance(code, int) and code >= 500:
            return VisionBusyError(f"Gemini service error ({code}): {detail}")
        return VisionError(f"Gemini vision failed (model '{self.model}'): {detail}")
