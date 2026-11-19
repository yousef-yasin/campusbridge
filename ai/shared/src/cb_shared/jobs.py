"""The loop shared by the per-unit AI features (summaries, questions): skip rules, cache,
manual edits, checks and failures that never stop the caller.

A subclass gives: kind, version, schema, prompt(unit), check(data, unit) -> problems.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional

from .cache import ReviewCache, has_manual, merged
from .errors import AIError, AILimitError, AIUnavailableError
from .units import TextUnit

log = logging.getLogger(__name__)


class UnitJob:
    kind = "job"
    version = 1
    schema: Dict[str, Any] = {}
    manual_template: Dict[str, Any] = {}
    min_words = 25

    def __init__(self, engine, cache_dir, language: str):
        self.engine = engine
        self.cache = ReviewCache(cache_dir)
        self.language = language
        self.model = getattr(engine, "model", "unknown")
        self.stopped: Optional[str] = None
        self.warnings: List[str] = []
        from .glossary import GlossaryError, load_glossary
        try:
            self.glossary = load_glossary()
        except GlossaryError as exc:
            self.glossary = None
            self._warn(f"glossary not used: {exc}")

    def glossary_rules(self, unit: TextUnit) -> str:
        """Meanings of the glossary terms on this unit, for the prompt ('' in en mode)."""
        rules = self.glossary.prompt_rules(unit.text, self.language) if self.glossary else ""
        return f"\n{rules}\n" if rules else ""

    def glossary_problems(self, texts) -> List[str]:
        """Arabic meanings next to glossary terms that differ from the glossary (ar and mixed)."""
        if not self.glossary or self.language == "en":
            return []
        return [f"term meaning differs from the glossary: {p}" for p in self.glossary.wrong_meanings(texts)]

    # --- to implement ------------------------------------------------------------------
    def prompt(self, unit: TextUnit) -> str:
        raise NotImplementedError

    def check(self, data: Dict[str, Any], unit: TextUnit) -> List[str]:
        return []

    # --- main --------------------------------------------------------------------------
    def skip_reason(self, unit: TextUnit) -> Optional[str]:
        if unit.is_title_unit():
            return "title slide"
        if unit.words < self.min_words:
            return f"too short ({unit.words} words, fewer than {self.min_words})"
        return None

    def run(self, units: Iterable[TextUnit]) -> List[Dict[str, Any]]:
        return [self.one(u) for u in units]

    def one(self, unit: TextUnit) -> Dict[str, Any]:
        base = {"unit": unit.number, "unit_type": unit.unit_type, "label": unit.label,
                "language": self.language}
        reason = self.skip_reason(unit)
        if reason:
            return dict(base, status="skipped", reason=reason)
        path = self.cache.path(unit.digest(), self.model, self.language, self.version, self.kind)
        record = self.cache.load(path)
        if record is None:
            if self.stopped:
                return dict(base, status="unavailable", reason=self.stopped)
            try:
                data = self.engine.generate_json(self.prompt(unit), self.schema)
            except AILimitError as exc:
                return self._stop(base, str(exc))
            except AIUnavailableError as exc:            # no key, quota, offline, all models busy
                return self._stop(base, str(exc))
            except AIError as exc:
                self._warn(f"{unit.label}: {self.kind} failed: {exc}")
                return dict(base, status="unavailable", reason=str(exc))
            for note in getattr(self.engine, "notes", [])[-1:]:
                self._warn(note)
            record = {"kind": self.kind, "unit": unit.label, "sha256": unit.digest(),
                      "model": getattr(self.engine, "last_model", None) or self.model,
                      "language": self.language, "version": self.version, "result": data,
                      "review": "draft", "manual": dict(self.manual_template,
                                                         note="fill in to replace the automatic result")}
            self.cache.save(path, record)
            cached = False
        else:
            cached = True
        manual = record.get("manual")
        result = merged(record.get("result") or {}, manual)
        problems = [] if has_manual(manual) else self.check(record.get("result") or {}, unit)
        status = "manual" if has_manual(manual) else ("needs_review" if problems else "ok")
        if problems and not cached:
            self._warn(f"{unit.label}: {self.kind} marked needs_review: {'; '.join(problems)}")
        return dict(base, **result, status=status, review=record.get("review", "draft"),
                    problems=problems, model=record.get("model"), cached=cached, cache_file=str(path))

    def _stop(self, base: Dict[str, Any], reason: str) -> Dict[str, Any]:
        self.stopped = reason
        self._warn(f"{self.kind}: stopped: {reason}. Remaining units have no {self.kind}.")
        return dict(base, status="unavailable", reason=reason)

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)
            log.warning(message)
