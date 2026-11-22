"""Page summaries (summary, key points linked to blocks, terms) and a summary of the whole file."""
import hashlib
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cb_shared import GeminiText, TextUnit, UnitBlock, UnitJob, missing_english, unverified_numbers

from .config import SummaryConfig, language_rules

PROMPT_VERSION = 2                       # 2: glossary meanings
_STR = {"type": "string"}

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": _STR,
        "points": {"type": "array", "items": {"type": "object", "properties": {
            "text": _STR, "block": _STR}, "required": ["text", "block"]}},
        "terms": {"type": "array", "items": {"type": "object", "properties": {
            "term": _STR, "meaning": _STR}, "required": ["term", "meaning"]}},
    },
    "required": ["summary", "points", "terms"],
}

PROMPT = """You help blind and visually impaired university students review lecture material \
by listening. Summarise ONE {unit} of the material below.

Strict rules:
- Use ONLY the text of this {unit}. Add no outside knowledge, no examples, no definitions that
  the text does not give. If something is not in the text, leave it out.
- Copy every number exactly as written. Never calculate, round or convert a number.
- summary: 2 to 3 sentences on what this {unit} says.
- points: the 3 to 5 most important points (fewer if the text has fewer). Each point names in
  "block" the id of the block it comes from (for example "b3"); one fact per point.
- terms: technical terms that appear in the text, written exactly as in the text, each with
  its meaning as the text explains or uses it. Leave out a term if the text gives no meaning
  for it. An empty list is fine.

Language: {language}
This applies to summary, points and meanings. A term stays as written in the text.
{glossary}
The {unit} ({label}), one line per block:
{content}"""

FILE_SCHEMA = {"type": "object", "properties": {"summary": _STR}, "required": ["summary"]}

FILE_PROMPT = """These are summaries of the pages of one lecture file, in order. Write a summary \
of the whole file in 4 to 6 sentences: what it covers and its main ideas, in the order of the \
file. Use ONLY these summaries; add nothing from outside. Copy numbers exactly as written.

Language: {language}

Title of the file: {title}
Page summaries:
{summaries}"""


def _texts(data: Dict[str, Any]) -> List[str]:
    out = [data.get("summary") or ""]
    out += [p.get("text") or "" for p in data.get("points") or [] if isinstance(p, dict)]
    out += [t.get("meaning") or "" for t in data.get("terms") or [] if isinstance(t, dict)]
    return out


class PageSummarizer(UnitJob):
    kind = "summary"
    version = PROMPT_VERSION
    schema = SCHEMA
    manual_template = {"summary": "", "points": [], "terms": []}

    def __init__(self, config: Optional[SummaryConfig] = None, engine=None, language: Optional[str] = None):
        self.config = config or SummaryConfig.from_env()
        mode, self.instruction = language_rules(language or self.config.language or None)
        super().__init__(engine or GeminiText(self.config.ai), self.config.cache_dir, mode)
        self.min_words = self.config.min_words

    def prompt(self, unit: TextUnit) -> str:
        return PROMPT.format(unit=unit.unit_type, label=unit.label, language=self.instruction,
                             content=unit.render(), glossary=self.glossary_rules(unit))

    def check(self, data: Dict[str, Any], unit: TextUnit) -> List[str]:
        problems = []
        numbers = unverified_numbers(_texts(data), [unit.text, unit.title])
        if numbers:
            problems.append(f"numbers not in the {unit.unit_type}: {', '.join(numbers)}")
        terms = [t.get("term") or "" for t in data.get("terms") or [] if isinstance(t, dict)]
        english = missing_english(terms if self.language == "en" else _texts(data) + terms, unit.text)
        if english:
            problems.append(f"English words not in the {unit.unit_type}: {', '.join(english)}")
        bad = [p.get("block") for p in data.get("points") or [] if isinstance(p, dict)
               and not unit.block(str(p.get("block")))]
        if bad:
            problems.append(f"points linked to blocks that do not exist: {', '.join(map(str, bad))}")
        problems += self.glossary_problems(_texts(data))
        if not (data.get("summary") or "").strip():
            problems.append("empty summary")
        return problems


class FileSummarizer:
    """A summary of the whole file, built only from the page summaries."""
    kind = "file_summary"

    def __init__(self, pages: PageSummarizer):
        self.pages = pages

    def summarize(self, results: List[Dict[str, Any]], units: List[TextUnit], title: str = "") -> Dict[str, Any]:
        usable = [r for r in results if r.get("status") in ("ok", "needs_review", "manual") and r.get("summary")]
        if not usable:
            return {"status": "skipped", "reason": "no page summaries"}
        lines = "\n".join(f"[{r['label']}] {r['summary']}" for r in usable)
        unit = TextUnit(0, "file", [UnitBlock("b1", "summaries", lines)], title)
        job = self.pages
        path = job.cache.path(hashlib.sha256(lines.encode("utf-8")).hexdigest(), job.model, job.language,
                              PROMPT_VERSION, self.kind)
        record = job.cache.load(path)
        if record is None:
            if job.stopped:
                return {"status": "unavailable", "reason": job.stopped}
            try:
                data = job.engine.generate_json(FILE_PROMPT.format(language=job.instruction, title=title or "(none)",
                                                                   summaries=lines), FILE_SCHEMA)
            except Exception as exc:
                job._warn(f"file summary failed: {exc}")
                return {"status": "unavailable", "reason": str(exc)}
            record = {"kind": self.kind, "sha256": unit.digest(), "model": getattr(job.engine, "last_model", None)
                      or job.model, "language": job.language, "version": PROMPT_VERSION, "result": data,
                      "review": "draft", "manual": {"summary": "", "note": "fill in to replace"}}
            job.cache.save(path, record)
        manual = (record.get("manual") or {}).get("summary", "").strip()
        summary = manual or record["result"].get("summary", "")
        source = [u.text for u in units] + [lines, title or ""]           # the title was given too
        numbers = [] if manual else unverified_numbers([summary], source)
        english = [] if manual or job.language == "en" else missing_english([summary], "\n".join(source))
        problems = ([f"numbers not in the file: {', '.join(numbers)}"] if numbers else []) + \
                   ([f"English words not in the file: {', '.join(english)}"] if english else [])
        return {"status": "manual" if manual else ("needs_review" if problems else "ok"), "summary": summary,
                "problems": problems, "pages": [r["unit"] for r in usable], "review": record.get("review"),
                "model": record.get("model"), "language": job.language, "cache_file": str(path)}


def summarize_units(units: Iterable[TextUnit], config: Optional[SummaryConfig] = None, engine=None,
                    language: Optional[str] = None, title: str = "",
                    file_summary: bool = True) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """(page results, file summary or None, warnings)."""
    units = list(units)
    pages = PageSummarizer(config, engine, language)
    results = pages.run(units)
    whole = FileSummarizer(pages).summarize(results, units, title) if file_summary else None
    return results, whole, pages.warnings
