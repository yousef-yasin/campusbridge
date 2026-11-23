"""Gemini text client shared by the CampusBridge AI modules (summaries, questions, ...).

generate_json(prompt, schema) -> dict. Text is sent to Google's servers. The API key comes from
GEMINI_API_KEY (process environment, else the given .env files) at request time; it is never
stored, logged or printed.

Robustness:
- 500/503 ("high demand") is retried after short pauses; the last try on a model drops the JSON
  schema (schema-constrained requests failed more often with 503 in our tests). Then the next
  model in the chain is used.
- 429 (quota) also moves to the next model, since free-tier limits are per model.
- 401/403, a missing key or no internet stop at once: other models would fail the same way.
- calls counts API requests; max_calls stops a run before it spends the daily quota.
"""
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .errors import AIBusyError, AIError, AILimitError, AIQuotaError, AIUnavailableError
from .keys import get_key, scrub

_AI = Path(__file__).resolve().parents[3]                    # ai/

# Free-tier text models, checked in Google's docs on 2026-11-19 (pricing and models pages):
# gemini-4-hydrogen, gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash-lite (all "Standard: free").
# On that day only 3.5 Flash-Lite answered a probe; Hydrogen gave 503 and 3.8/3.6 Flash timed out
# (504), so Flash-Lite comes first and the others are the fallback chain.
DEFAULT_MODELS = ("gemini-3.5-flash-lite", "gemini-4-hydrogen", "gemini-3.8-flash")


def http_options(timeout_s: int):
    """google-genai HttpOptions. CB_GEMINI_IPV4=1 connects over IPv4 only: on a network where
    IPv6 to Google does not work, the first request otherwise waits minutes for IPv6 to fail."""
    import os
    from google.genai import types
    args = {}
    if os.environ.get("CB_GEMINI_IPV4", "").strip().lower() in ("1", "true", "yes"):
        try:
            import httpx2 as httpx                   # the fork google-genai 3.x installs
        except ImportError:
            import httpx
        args["client_args"] = {"transport": httpx.HTTPTransport(local_address="0.0.0.0")}
    return types.HttpOptions(timeout=timeout_s * 1000, **args)


@dataclass
class GeminiTextConfig:
    models: Sequence[str] = DEFAULT_MODELS        # tried in order
    env_files: Sequence[str] = field(default_factory=lambda: [str(_AI / "document-reader" / ".env")])
    timeout: int = 90                             # seconds per request
    temperature: float = 0.2
    thinking: str = "low"                         # Gemini thinking level ("" = model default)
    retry_pauses: Sequence[float] = (5.0, 15.0)   # waits after a 500/503 on the same model
    max_calls: int = 30                           # API requests per run (0 = no request at all)

    @classmethod
    def from_env(cls, prefix: str = "AI", env_files: Optional[Iterable[str]] = None) -> "GeminiTextConfig":
        """Settings from <prefix>_MODELS (comma list), <prefix>_MAX_CALLS, <prefix>_TIMEOUT, <prefix>_THINKING."""
        import os
        e = os.environ.get
        cfg = cls()
        if e(f"{prefix}_MODELS"):
            cfg.models = tuple(m.strip() for m in e(f"{prefix}_MODELS").split(",") if m.strip())
        cfg.max_calls = int(e(f"{prefix}_MAX_CALLS", cfg.max_calls))
        cfg.timeout = int(e(f"{prefix}_TIMEOUT", cfg.timeout))
        cfg.thinking = e(f"{prefix}_THINKING", cfg.thinking)
        if env_files is not None:
            cfg.env_files = list(env_files)
        if e(f"{prefix}_ENV_FILE"):                   # one explicit .env file (tests: never the real key)
            cfg.env_files = [e(f"{prefix}_ENV_FILE")]
        if not cfg.models:
            raise ValueError(f"{prefix}_MODELS must name at least one model")
        return cfg


class GeminiText:
    """generate_json(prompt, schema) -> (dict, model used)."""
    name = "gemini"

    def __init__(self, config: Optional[GeminiTextConfig] = None, client=None):
        self.config = config or GeminiTextConfig()
        self._client = client                      # injected client (tests)
        self.calls = 0
        self.last_model: Optional[str] = None
        self.notes: List[str] = []                 # model switches, for warnings

    @property
    def model(self) -> str:
        """The first model of the chain (used in cache keys)."""
        return self.config.models[0]

    def _get_client(self, key: str):
        if self._client is not None:
            return self._client
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise AIUnavailableError(f"google-genai is not installed (pip install google-genai): {exc}") from exc
        if not key:
            where = ", ".join(str(p) for p in self.config.env_files) or "the environment"
            raise AIUnavailableError(f"GEMINI_API_KEY is not set (environment, or one of: {where})")
        return genai.Client(api_key=key, http_options=http_options(self.config.timeout))

    def generate_json(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        key = get_key("GEMINI_API_KEY", self.config.env_files)
        client = self._get_client(key)
        errors: List[AIError] = []
        for model in self.config.models:
            attempts = [schema] * len(self.config.retry_pauses) + [None]
            for number, attempt_schema in enumerate(attempts):
                if self.calls >= self.config.max_calls:
                    raise AILimitError(f"limit of {self.config.max_calls} AI requests per run reached")
                self.calls += 1
                try:
                    text = self._request(client, model, prompt, attempt_schema)
                except Exception as exc:
                    error = self._error(exc, key, model)
                    if isinstance(error, (AIBusyError, AIQuotaError)) and not isinstance(error, _Stop):
                        if isinstance(error, AIBusyError) and number < len(attempts) - 1:
                            time.sleep(self.config.retry_pauses[min(number, len(self.config.retry_pauses) - 1)])
                            continue
                        errors.append(error)
                        break                                   # next model
                    raise error from None
                data = self._parse(text, schema)
                if model != self.config.models[0]:
                    self.notes.append(f"{self.config.models[0]} failed ({errors[-1] if errors else '?'}); used {model}")
                self.last_model = model
                return data
        if errors and all(isinstance(e, AIQuotaError) for e in errors):
            raise AIQuotaError("all models: " + " | ".join(map(str, errors)))
        if errors and all(isinstance(e, AIUnavailableError) for e in errors):
            raise AIBusyError("all models busy or out of quota: " + " | ".join(map(str, errors)))
        raise AIError(" | ".join(map(str, errors)) or "no model answered")

    def _request(self, client, model: str, prompt: str, schema) -> str:
        from google.genai import types
        settings = {"response_mime_type": "application/json", "temperature": self.config.temperature}
        if schema:
            settings["response_json_schema"] = schema
        if self.config.thinking:
            settings["thinking_config"] = types.ThinkingConfig(thinking_level=self.config.thinking)
        response = client.models.generate_content(model=model, contents=prompt,
                                                  config=types.GenerateContentConfig(**settings))
        return response.text or ""

    @staticmethod
    def _parse(text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = json.loads(text)
        except ValueError:
            raise AIError(f"the model returned no valid JSON: {text[:120]!r}") from None
        if isinstance(data, list):              # a bare array answers the schema's first array field
            name = next((k for k in schema.get("required", [])
                         if (schema.get("properties", {}).get(k) or {}).get("type") == "array"), None)
            data = {name: data} if name else data
        if not isinstance(data, dict):
            raise AIError("the model returned JSON that is not an object")
        missing = [f for f in schema.get("required", []) if f not in data]
        if missing:
            raise AIError(f"the model answer is missing {', '.join(missing)}")
        return data

    def _error(self, exc: Exception, key: str, model: str) -> AIError:
        code = getattr(exc, "code", None)
        detail = scrub(f"{type(exc).__name__}: {getattr(exc, 'message', None) or exc}", key)[:300]
        if code == 429:
            match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(getattr(exc, "details", "")))
            return AIQuotaError(f"{model}: quota or rate limit exceeded (429): {detail}",
                                float(match.group(1)) if match else 0.0)
        if code in (401, 403):
            return _Stop(f"Gemini rejected the API key ({code}): {detail}")
        module = type(exc).__module__
        if isinstance(exc, (OSError, TimeoutError)) or module.startswith(("httpx", "httpcore", "aiohttp")):
            return _Stop(f"Gemini unreachable (internet required): {detail}")
        if isinstance(code, int) and code >= 500:
            return AIBusyError(f"{model}: service error ({code}): {detail}")
        if code == 404:
            return AIQuotaError(f"{model}: model not found (404): {detail}")   # try the next model
        return AIError(f"{model}: {detail}")


class _Stop(AIUnavailableError):
    """Key rejected or no internet: no point trying other models."""
