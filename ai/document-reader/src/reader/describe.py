"""Phase 2: describe the images of a document with a vision model.

Each image block gets a category, a short and a detailed description, the text written inside
it, and category data (table rows, chart values, diagram relations, a spoken equation).
Results are cached as reviewable JSON files; a manual description in that file wins over the
automatic one. Network problems never stop the reader: the image is marked "undescribed".

Images, the page title and the text around each image are sent to the vision model (Google).
"""
import io
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import ReaderConfig
from .errors import VisionBusyError, VisionError, VisionQuotaError, VisionUnavailableError
from .explain import INSTRUCTIONS, explain_language
from .lang import clean_text
from .model import Block, Page
from .numbers import unverified_numbers
from .tables import make_table

log = logging.getLogger(__name__)

PROMPT_VERSION = 4                         # bump when the prompt, schema or language rules change
CATEGORIES = ("table", "chart", "diagram", "equation", "text", "screenshot", "photo", "decorative")
_SENDABLE = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_MAX_SIDE = 2048                           # larger images are scaled down before sending
_CONTEXT_CHARS = 500
_BUSY_LIMIT = 3                            # stop after this many overloaded answers in a row

_STR = {"type": "string"}
SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "short_description": _STR,
        "detailed_description": _STR,
        "text_in_image": _STR,
        "table": {"type": "object", "properties": {
            "columns": {"type": "array", "items": _STR},
            "rows": {"type": "array", "items": {"type": "array", "items": _STR}}}},
        "chart": {"type": "object", "properties": {
            "chart_type": _STR, "x_axis": _STR, "y_axis": _STR,
            "key_values": {"type": "array", "items": _STR}, "trend": _STR}},
        "diagram": {"type": "object", "properties": {
            "elements": {"type": "array", "items": _STR},
            "relations": {"type": "array", "items": _STR}}},
        "equation": {"type": "object", "properties": {"written": _STR, "spoken": _STR}},
        "photo": {"type": "object", "properties": {"role": _STR}},
        "informative": {"type": "boolean"},
    },
    "required": ["category", "short_description", "detailed_description", "text_in_image"],
}

PROMPT = """You describe one image from university lecture material for blind and visually \
impaired students who will hear your description read aloud.

Where the image appears: {where}
Title of this {unit}: {title}
Text around the image in the material:
{context}

0. informative: true only if the image shows information the student needs for the lesson:
   data, values, structure, steps, labels, an example, an experiment, a real object being studied.
   false if it only sets a mood or illustrates the topic in general, even when it fits the topic:
   a person at a computer or in front of screens, people in a meeting, generic charts used as
   decoration, backgrounds, ornaments, logos, icons, clip art, stock photos, the picture of a
   title slide.
1. category: one of table, chart, diagram, equation, text, screenshot, photo, decorative.
   decorative = any image with informative false.
2. short_description: one or two sentences saying what the image shows and why it matters here.
3. detailed_description: a complete explanation for a student who cannot see the image.
4. text_in_image: every piece of text visible in the image, exactly as written, in its original
   language and script, without translating or correcting it. Empty string if there is none.
5. Fill the object for the category:
   table: columns and rows exactly as in the image (cell text as written).
   chart: chart_type, x_axis, y_axis, key_values (the main values), trend (overall direction).
   diagram: elements, and relations between them in a logical reading order.
   equation: written (as text, e.g. z = (x - mu) / sigma) and spoken (how to read it aloud).
   photo: role (its role in the lesson).

Language: {language}
This applies to short_description, detailed_description, trend, relations, spoken and role.
It never applies to text_in_image or table cells, which stay exactly as written.
Numbers: copy every number exactly as it is written in the image, in digits. Never calculate,
add, subtract, round, convert or estimate a number, and never write numbers in words. If a value
is not written in the image, do not state it.
Describe only what is visible; if something is unreadable, say so. Do not invent values."""

# Fields written by the model in the explanation language; their numbers are checked.
_EXPLAINED = (("short_description",), ("detailed_description",), ("chart", "trend"),
              ("chart", "key_values"), ("diagram", "elements"), ("diagram", "relations"),
              ("equation", "spoken"), ("photo", "role"))


def _texts(result: dict, path) -> List[str]:
    value = result
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def check_numbers(result: dict, context: Iterable[str] = ()) -> List[str]:
    """Numbers in the explanation that are not in the image text, table cells or page text."""
    described = [t for path in _EXPLAINED for t in _texts(result, path)]
    table = result.get("table") if isinstance(result.get("table"), dict) else {}
    cells = [str(c) for c in table.get("columns") or []]
    cells += [str(c) for row in table.get("rows") or [] if isinstance(row, list) for c in row]
    sources = [result.get("text_in_image") or ""] + cells + list(context)
    return unverified_numbers(described, sources)


class ImageDescriber:
    """Fills image blocks of pages with descriptions from a vision engine."""

    def __init__(self, config: Optional[ReaderConfig] = None, engine=None, language: Optional[str] = None):
        self.config = (config or ReaderConfig.from_env()).validate()
        self.language = explain_language(language)
        if engine is None:
            from .vision import GeminiVision
            engine = GeminiVision(self.config)
        self.engine = engine
        self.model = getattr(engine, "model", None) or self.config.vision_model
        self.cache_dir = Path(self.config.descriptions_dir)
        self.calls = 0
        self.stopped: Optional[str] = None    # set after a quota/unavailable error: no more calls
        self.busy_in_a_row = 0
        self.warnings: List[str] = []

    # --- cache -------------------------------------------------------------------------
    def cache_path(self, sha: str) -> Path:
        model = re.sub(r"[^A-Za-z0-9._-]+", "_", self.model)
        return self.cache_dir / f"{sha[:16]}__{model}__{self.language}__v{PROMPT_VERSION}.json"

    def _load(self, sha: str) -> Optional[dict]:
        try:
            return json.loads(self.cache_path(sha).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self, sha: str, record: dict) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_path(sha).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Description cache not written: %s", exc)

    # --- input -------------------------------------------------------------------------
    @staticmethod
    def _prepare(path: str):
        """(bytes, mime) in a format the model accepts, scaled down if very large."""
        from PIL import Image
        blob = Path(path).read_bytes()
        with Image.open(io.BytesIO(blob)) as im:
            fmt = im.format
            if fmt in _SENDABLE and max(im.size) <= _MAX_SIDE:
                return blob, _SENDABLE[fmt]
            im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
            im.thumbnail((_MAX_SIDE, _MAX_SIDE))
            out = io.BytesIO()
            im.save(out, "PNG")
            return out.getvalue(), "image/png"

    @staticmethod
    def _context(page: Page, index: int):
        title = next((b.text for b in page.blocks if b.kind == "heading"), "") or "(none)"
        before = [b.text for b in page.blocks[:index] if b.kind != "image" and b.text][-3:]
        after = [b.text for b in page.blocks[index + 1:] if b.kind != "image" and b.text][:3]
        text = "\n".join(before)[-_CONTEXT_CHARS:] + "\n[IMAGE]\n" + "\n".join(after)[:_CONTEXT_CHARS]
        return title, text.strip()

    def prompt(self, page: Page, index: int) -> str:
        title, context = self._context(page, index)
        where = f"{page.unit_type} {page.sheet or page.unit}"
        return PROMPT.format(where=where, unit=page.unit_type, title=title, context=context,
                             language=INSTRUCTIONS[self.language])

    # --- results -----------------------------------------------------------------------
    @staticmethod
    def _apply(image: dict, record: dict, context: Iterable[str] = ()) -> None:
        result = record.get("result") or {}
        manual = record.get("manual") or {}
        category = result.get("category") if result.get("category") in CATEGORIES else "photo"
        if result.get("informative") is False and category == "photo":
            category = "decorative"         # a photo that carries no lesson information is skipped
        image.update({
            "category": category,
            "description": clean_text(result.get("short_description", "")),
            "details": clean_text(result.get("detailed_description", "")),
            "text": (result.get("text_in_image") or "").strip(),
            "status": "decorative" if category == "decorative" else "described",
            "language": record.get("language"), "model": record.get("model"),
        })
        for name in ("chart", "diagram", "equation", "photo"):
            if result.get(name):
                image[name] = result[name]
        if category == "table" and result.get("table"):
            rows = [result["table"].get("columns") or []] + (result["table"].get("rows") or [])
            table = make_table(rows)
            if table:
                image["table"] = table
        unverified = check_numbers(result, context)
        image.pop("unverified_numbers", None)
        if unverified and category != "decorative":
            image["status"] = "needs_review"
            image["unverified_numbers"] = unverified
        if (manual.get("short") or "").strip():
            image["description"] = manual["short"].strip()
            image["details"] = (manual.get("detailed") or "").strip() or image["description"]
            image["status"] = "manual"
            image.pop("unverified_numbers", None)
        image.pop("reason", None)

    @staticmethod
    def _undescribed(image: dict, reason: str) -> None:
        image.update({"status": "undescribed", "reason": reason})

    # --- main --------------------------------------------------------------------------
    def describe_pages(self, pages: Iterable[Page]) -> List[str]:
        """Describe every image block in the pages (in place). Returns the warnings."""
        for page in pages:
            for index, block in enumerate(page.blocks):
                if block.kind == "image" and block.image:
                    self._describe(page, index, block)
        return self.warnings

    def _describe(self, page: Page, index: int, block: Block) -> None:
        image = block.image
        sha = image.get("sha256", "")
        title, context = self._context(page, index)
        record = self._load(sha) if sha else None
        if record:
            self._apply(image, record, (title, context))
            return
        if self.stopped:
            self._undescribed(image, self.stopped)
            return
        if self.calls >= self.config.vision_max_images:
            self._undescribed(image, f"limit of {self.config.vision_max_images} images per run reached")
            self._warn(f"image limit reached ({self.config.vision_max_images} per run, "
                       f"READER_VISION_MAX_IMAGES): remaining images are not described")
            return
        path = image.get("path")
        if not path or not Path(path).is_file():
            self._undescribed(image, "image file not saved (extract_images is off)")
            self._warn("some images were not saved (extract_images is off), so they cannot be described")
            return
        try:
            data, mime = self._prepare(path)
        except Exception as exc:
            self._undescribed(image, f"image format not supported ({image.get('ext')}): {exc}")
            self._warn(f"{page.label}: an image in .{image.get('ext')} format could not be sent")
            return
        prompt = self.prompt(page, index)
        result = self._call(data, mime, prompt, image, page)
        if result is None:
            return
        record = {"sha256": sha, "model": self.model, "language": self.language,
                  "prompt_version": PROMPT_VERSION,
                  "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "source": {"where": f"{page.unit_type} {page.sheet or page.unit}"},
                  "result": result,
                  "manual": {"short": "", "detailed": "",
                             "note": "write here to replace the automatic description"}}
        unverified = check_numbers(result, (title, context))
        record["number_check"] = {"needs_review": bool(unverified), "unverified_numbers": unverified}
        self._save(sha, record)
        self._apply(image, record, (title, context))
        if unverified:
            self._warn(f"{page.label}: the description has numbers not found in the image "
                       f"({', '.join(unverified)}); marked needs_review, speech reads the image text")

    def _call(self, data, mime, prompt, image, page) -> Optional[dict]:
        for attempt in (1, 2):
            self.calls += 1
            try:
                result = self.engine.describe(data, mime, prompt, SCHEMA)
                self.busy_in_a_row = 0
                return result
            except VisionBusyError as exc:          # temporary overload: try the next image
                self.busy_in_a_row += 1
                if self.busy_in_a_row >= _BUSY_LIMIT:
                    return self._stop(image, f"{exc} ({_BUSY_LIMIT} images in a row)")
                self._undescribed(image, str(exc))
                self._warn(f"the vision service is overloaded (503); {page.label}: image not described, "
                           f"run again later to describe it")
                return None
            except VisionQuotaError as exc:
                wait = exc.retry_after or self.config.vision_retry_wait
                if attempt == 1 and 0 < wait <= self.config.vision_retry_wait:
                    log.warning("Vision rate limit, retrying in %.0fs", wait)
                    time.sleep(wait)
                    continue
                return self._stop(image, str(exc))
            except VisionUnavailableError as exc:
                return self._stop(image, str(exc))
            except VisionError as exc:
                self._undescribed(image, str(exc))
                self._warn(f"{page.label}: an image could not be described: {exc}")
                return None
        return None

    def _stop(self, image, reason: str):
        self.stopped = reason
        self._undescribed(image, reason)
        self._warn(f"image descriptions stopped: {reason}. Remaining images are marked undescribed.")
        return None

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)
            log.warning(message)
