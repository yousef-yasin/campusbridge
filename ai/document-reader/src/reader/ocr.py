"""Phase 4: OCR, the text inside page images (scanned PDF pages and photos of paper).

Pages are read one by one, only when asked, with the same Gemini vision model as the image
descriptions. Pages are sent to Google. The answer is the unified structure (heading,
paragraph, list and table blocks, in reading order), marked source="ocr". Text is copied
exactly as written; words that cannot be read are marked UNCLEAR instead of guessed.

Results are cached per page-image hash, model and prompt version (ocr-cache/). When Gemini
cannot be used (no key, quota, no internet, overloaded), Tesseract (ara+eng) is used if it is
installed, with a warning that the quality is lower. Without it, the page stays "needs OCR".
"""
import csv
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import ReaderConfig
from .errors import VisionBusyError, VisionError, VisionQuotaError, VisionUnavailableError
from .explain import explain_language
from .images import digest
from .lang import detect_language
from .model import Block, Page
from .tables import make_table, table_text

log = logging.getLogger(__name__)

PROMPT_VERSION = 3                         # bump when the prompt or schema change
UNCLEAR = "[unclear]"                      # stored in the text where a word could not be read
_TESSERACT_HOME = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe"
_MIN_CONFIDENCE = 30                       # Tesseract words below this confidence are UNCLEAR
_INSTALL = ("Tesseract is not installed, so pages cannot be read without Gemini. To install it: "
            "Windows: https://github.com/UB-Mannheim/tesseract/wiki (tick Arabic in 'Additional "
            "language data'), or `winget install UB-Mannheim.TesseractOCR`; Ubuntu: "
            "`sudo apt install tesseract-ocr tesseract-ocr-ara`; macOS: `brew install tesseract "
            "tesseract-lang`. Set READER_TESSERACT if it is not on PATH.")

_STR = {"type": "string"}
SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["heading", "paragraph", "list", "table", "handwritten"]},
                "level": {"type": "integer"},
                "text": _STR,
                "items": {"type": "array", "items": _STR},
                "rows": {"type": "array", "items": {"type": "array", "items": _STR}},
            },
            "required": ["kind"]}},
        "language": _STR,
    },
    "required": ["blocks"],
}

PROMPT = f"""You transcribe one page image (a scanned page or a photo of paper) of university \
material for blind and visually impaired students. The text will be read aloud.

Rules:
1. Copy the text exactly as written: same words, spelling, numbers, symbols and language. Never
   translate, summarise, explain, correct mistakes (not even spelling or hamza) or complete
   missing text. Keep every punctuation mark where it is, including the Arabic comma (،), the
   colon (:), the semicolon (؛), brackets and dashes: do not drop or add any.
2. If a word cannot be read with confidence, write {UNCLEAR} in its place. Never guess a word.
   If a whole line is unreadable, write {UNCLEAR} once for it.
3. Natural reading order. Arabic is read right to left: in Arabic pages with columns, read the
   right column first; in English pages, the left column first. Keep each line's words in
   their reading order.
4. Return blocks in that order:
   heading: a title or section title, with level 1 (main) to 3;
   paragraph: running text (join the lines of one paragraph with spaces);
   list: numbered or bulleted items, one string per item, keeping the item's number or letter;
   table: rows of cells, the header row first, every cell exactly as written ("" if empty).
   Use table only for a real grid of rows and columns. Labels or boxes placed around a picture
   or a diagram are not a table: give them as a list, in reading order.
   handwritten: a note written by hand (between lines, above a word, in the margin), as its
   own block placed right after the printed block it belongs to. Copy it exactly as written,
   in its own language; use [unclear] for words you cannot read. Never mix handwriting into
   the printed blocks, and never put printed text into a handwritten block.
5. Include page headers, footers and page numbers only if they are part of the content.
   Ignore stamps, folds, shadows and anything that is not text (handwriting is text: rule 4).
6. language: "ar", "en" or "mixed".
If the image has no readable text, return an empty list of blocks."""


# --- result -> blocks ---------------------------------------------------------------------

_ARABIC = re.compile(r"[\u0600-\u06FF]")
_MOVED_MARK = re.compile(r"(?<=\S) ([.\u060C\u061B:!\u061F])(?=[\u0600-\u06FF])")


def _clean(text: Any) -> str:
    """Whitespace normalised. In Arabic text, a mark the model moved to the start of the next
    word («السنين .وهي», a right-to-left artifact) is put back: «السنين. وهي». No word changes."""
    text = " ".join(str(text or "").split())
    return _MOVED_MARK.sub(r"\1 ", text) if _ARABIC.search(text) else text


def to_blocks(result: Dict[str, Any], unit: int, unit_type: str = "page") -> List[Block]:
    """The engine's answer as unified blocks, marked source="ocr"."""
    out: List[Block] = []
    for item in result.get("blocks") or []:
        if not isinstance(item, dict):
            continue
        # Without the schema (last retry) the model sometimes writes "type" instead of "kind".
        kind = item.get("kind") or item.get("type")
        if kind not in ("heading", "paragraph", "list", "table", "handwritten"):
            kind = "table" if item.get("rows") else "list" if item.get("items") else "paragraph"
        if kind == "table":
            rows = [[_clean(c) for c in row] for row in item.get("rows") or [] if isinstance(row, list)]
            table = make_table(rows) if rows else None
            if table:
                out.append(Block("table", table_text(table), detect_language(table_text(table)), unit,
                                 unit_type, table=table, source="ocr"))
            continue
        if kind == "list":
            items = [_clean(i) for i in item.get("items") or [] if _clean(i)]
            if not items and _clean(item.get("text")):
                items = [_clean(line) for line in str(item["text"]).split("\n") if _clean(line)]
            if items:
                text = "\n".join(items)
                out.append(Block("list", text, detect_language(text), unit, unit_type, items=items, source="ocr"))
            continue
        text = _clean(item.get("text"))
        if not text:
            continue
        if kind == "handwritten":
            out.append(Block("handwritten", text, detect_language(text), unit, unit_type, source="ocr"))
        elif kind == "heading":
            level = item.get("level") if isinstance(item.get("level"), int) else 1
            out.append(Block("heading", text, detect_language(text), unit, unit_type,
                             level=min(max(level, 1), 3), source="ocr"))
        else:
            out.append(Block("paragraph", text, detect_language(text), unit, unit_type, source="ocr"))
    return out


# --- Tesseract (local fallback) -------------------------------------------------------------

class Tesseract:
    """Runs the tesseract program (not installed by this module)."""

    def __init__(self, config: ReaderConfig):
        self.config = config
        self.path = self.find(config)
        self._langs: Optional[List[str]] = None

    @staticmethod
    def find(config: ReaderConfig) -> Optional[str]:
        for candidate in (config.tesseract, shutil.which("tesseract"), str(_TESSERACT_HOME)):
            if candidate and Path(candidate).is_file():
                return candidate
        return None

    def languages(self) -> List[str]:
        if self._langs is None:
            out = subprocess.run([self.path, "--list-langs"], capture_output=True, text=True, timeout=30)
            self._langs = [l.strip() for l in out.stdout.splitlines()[1:] if l.strip()]
        return self._langs

    def missing_languages(self) -> List[str]:
        return [l for l in self.config.tesseract_langs.split("+") if l not in self.languages()]

    def read(self, image: bytes) -> Dict[str, Any]:
        """{"blocks": [...]} like the Gemini answer: one paragraph per Tesseract paragraph."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "page.png"
            from PIL import Image
            with Image.open(io.BytesIO(image)) as im:
                im.convert("RGB").save(src, "PNG")
            run = subprocess.run([self.path, str(src), "stdout", "-l", self.config.tesseract_langs,
                                  "--psm", "3", "tsv"], capture_output=True, timeout=300)
            if run.returncode != 0:
                raise VisionError(f"tesseract failed: {run.stderr.decode('utf-8', 'replace')[:200]}")
        return {"blocks": parse_tsv(run.stdout.decode("utf-8", "replace")), "language": ""}


def parse_tsv(tsv: str) -> List[Dict[str, Any]]:
    """Tesseract TSV -> paragraph blocks; low-confidence words become UNCLEAR."""
    paragraphs: Dict[tuple, Dict[tuple, List[str]]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        if row.get("level") != "5" or not word:
            continue
        try:
            confidence = float(row.get("conf") or -1)
        except ValueError:
            confidence = -1
        key = (int(row["block_num"]), int(row["par_num"]))
        line = paragraphs.setdefault(key, {}).setdefault(int(row["line_num"]), [])
        line.append(word if confidence >= _MIN_CONFIDENCE else UNCLEAR)
    blocks = []
    for key in sorted(paragraphs):
        lines = [" ".join(words) for _, words in sorted(paragraphs[key].items())]
        text = re.sub(rf"(?:{re.escape(UNCLEAR)}\s*){{2,}}", UNCLEAR + " ", " ".join(lines)).strip()
        if text and text != UNCLEAR:
            blocks.append({"kind": "paragraph", "text": text})
    return blocks


# --- the reader -----------------------------------------------------------------------------

class PageOCR:
    """Reads the text of pages that need OCR (in place), one page at a time."""

    def __init__(self, config: Optional[ReaderConfig] = None, engine=None, language: Optional[str] = None,
                 tesseract: Any = "auto"):
        self.config = (config or ReaderConfig.from_env()).validate()
        self.language = explain_language(language)      # how speech announces the OCR text
        if engine is None:
            from .vision import GeminiVision
            engine = GeminiVision(self.config)
        self.engine = engine
        self.model = getattr(engine, "model", None) or self.config.vision_model
        self.tesseract = Tesseract(self.config) if tesseract == "auto" else tesseract
        self.cache_dir = Path(self.config.ocr_dir)
        self.calls = 0
        self.offline: Optional[str] = None    # why Gemini is not used for the rest of the run
        self.warnings: List[str] = []

    # --- cache -------------------------------------------------------------------------
    def cache_path(self, sha: str) -> Path:
        model = re.sub(r"[^A-Za-z0-9._-]+", "_", self.model)
        return self.cache_dir / f"{sha[:16]}__{model}__v{PROMPT_VERSION}.json"

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
            log.warning("OCR cache not written: %s", exc)

    # --- input -------------------------------------------------------------------------
    def _page_image(self, doc, n: int):
        from PIL import Image
        blob, mime = doc.page_image(n, self.config.ocr_dpi)
        with Image.open(io.BytesIO(blob)) as im:
            if max(im.size) <= self.config.ocr_max_side:
                return blob, mime
            im = im.convert("RGB")
            im.thumbnail((self.config.ocr_max_side, self.config.ocr_max_side))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=90)
            return out.getvalue(), "image/jpeg"

    # --- main --------------------------------------------------------------------------
    def read_pages(self, doc, pages: Iterable[Page]) -> List[str]:
        """OCR every page that needs it (in place). Returns the warnings."""
        for page in pages:
            if page.needs_ocr:
                self.read_page(doc, page)
        return self.warnings

    def read_page(self, doc, page: Page) -> Page:
        if not page.needs_ocr or (page.ocr and page.ocr.get("status") == "done"):
            return page
        try:
            image, mime = self._page_image(doc, page.unit)
        except Exception as exc:
            return self._needs_ocr(page, f"the page image could not be made: {exc}")
        sha = digest(image)
        record = self._load(sha)
        if record:
            return self._apply(page, record["result"], "gemini", record.get("model"), cached=True)
        reason = self.offline
        if reason is None and self.calls >= self.config.ocr_max_pages:
            reason = f"limit of {self.config.ocr_max_pages} pages per run reached (READER_OCR_MAX_PAGES)"
        if reason is None:
            try:
                self.calls += 1
                result = self.engine.describe(image, mime, PROMPT, SCHEMA)
                self._save(sha, {"sha256": sha, "model": self.model, "prompt_version": PROMPT_VERSION,
                                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "source": {"file": doc.path.name, "page": page.unit}, "result": result})
                return self._apply(page, result, "gemini", self.model)
            except VisionBusyError as exc:
                reason = str(exc)                                 # this page only
            except (VisionQuotaError, VisionUnavailableError) as exc:
                reason = self.offline = str(exc)                  # no more Gemini calls in this run
            except VisionError as exc:
                reason = str(exc)
        return self._fallback(page, image, reason)

    def _fallback(self, page: Page, image: bytes, reason: str) -> Page:
        tess = self.tesseract
        if not tess or not getattr(tess, "path", None):
            self._warn(f"OCR with Gemini is not possible ({reason}). {_INSTALL}")
            return self._needs_ocr(page, reason)
        missing = tess.missing_languages()
        if missing:
            self._warn(f"Tesseract is installed but lacks the language data {', '.join(missing)}; "
                       f"add it (Arabic: ara.traineddata in tessdata)")
            return self._needs_ocr(page, f"{reason}; tesseract has no {', '.join(missing)}")
        try:
            result = tess.read(image)
        except Exception as exc:
            return self._needs_ocr(page, f"{reason}; tesseract failed: {exc}")
        self._warn(f"OCR with Gemini is not possible ({reason}); used Tesseract "
                   f"({self.config.tesseract_langs}) instead: the text quality is lower, check it")
        return self._apply(page, result, "tesseract", None)

    def _apply(self, page: Page, result: Dict[str, Any], engine: str, model: Optional[str],
               cached: bool = False) -> Page:
        blocks = to_blocks(result, page.unit, page.unit_type)
        unclear = sum(b.text.count(UNCLEAR) for b in blocks)
        page.ocr = {"status": "done", "engine": engine, "model": model, "language": self.language,
                    "cached": cached, "blocks": len(blocks), "unclear_words": unclear}
        if not blocks:
            page.ocr["status"] = "no_text"
            page.warnings.append("OCR found no readable text on this page")
            return page
        # The page image itself is replaced by its text; other pictures are kept.
        page.blocks = blocks + [b for b in page.blocks if b.kind == "image" and not _page_scan(b)]
        from .references import mark_references
        mark_references(page)                    # footnotes at the bottom of the scanned page
        if unclear:
            page.warnings.append(f"OCR: {unclear} unclear word(s) marked {UNCLEAR}")
        return page

    def _needs_ocr(self, page: Page, reason: str) -> Page:
        page.ocr = {"status": "needs_ocr", "reason": reason, "language": self.language}
        return page

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)
            log.warning(message)


def _page_scan(block: Block) -> bool:
    """The image that is the page itself (a photo file, or a scan covering a PDF page)."""
    image = block.image or {}
    return bool(image.get("page_image") or image.get("covers_page"))
