"""PDF with a text layer (PyMuPDF). Scanned pages are reported as needing OCR.

All PyMuPDF use is in this file, so the PDF library can be replaced without touching the rest.
"""
import re
from collections import Counter
from statistics import median
from typing import Dict, List, Optional, Set

from .document import Document
from .errors import CorruptFileError, PasswordProtectedError
from .images import is_decoration
from .lang import clean_text, detect_language, fix_visual_order, is_rtl
from .layout import order_boxes, split_columns
from .model import Block, OutlineEntry, Page
from .tables import make_table, table_text

_BULLET = re.compile(r"^\s*(?:[•●▪◦○■□➢►–—\-*-]"
                     r"|\(?[0-9٠-٩]{1,2}[.)\-]\s)")
_JUNK_TITLE = re.compile(r"^(microsoft (word|powerpoint)\s*-|powerpoint presentation|untitled|"
                         r"presentation\d*$|document\d*$)|\.(docx?|pptx?|pdf)$", re.I)
_GARBLED = re.compile("[ء-ي][ƀ-ɏ]|[ƀ-ɏ][ء-ي]")
_MIN_DISPLAY = 20       # points: images drawn smaller than this are icons
_END_PUNCT = tuple(".:؛;؟?!،,")


class PdfDocument(Document):
    file_type = "pdf"
    unit_type = "page"

    def __init__(self, path, config):
        super().__init__(path, config)
        import pymupdf
        self._fitz = pymupdf
        try:
            self._doc = pymupdf.open(str(path))
        except Exception as exc:
            raise CorruptFileError(f"Cannot open {path.name} as PDF: {exc}") from exc
        if self._doc.needs_pass:
            self._doc.close()
            raise PasswordProtectedError(f"{path.name} is password protected")
        self._repeated: Optional[Set[int]] = None

    def close(self) -> None:
        self._doc.close()

    @property
    def unit_count(self) -> int:
        return self._doc.page_count

    def _repeated_images(self) -> Set[int]:
        """Image objects drawn on most pages (logos, backgrounds). Reads no image data."""
        if self._repeated is None:
            counts = Counter()
            for i in range(self._doc.page_count):     # reads each page's image list, not the page
                counts.update({img[0] for img in self._doc.get_page_images(i, full=True)})
            n = self._doc.page_count
            limit = max(3, self.config.repeated_image_ratio * n)
            self._repeated = {x for x, c in counts.items() if n >= 3 and c >= limit}
        return self._repeated

    # --- text --------------------------------------------------------------------------
    @staticmethod
    def _rows(lines):
        """Merge MuPDF lines on the same baseline (bidi runs) into visual rows, in reading order."""
        rows = []
        for line in sorted(lines, key=lambda l: l["bbox"][1]):
            text = "".join(s["text"] for s in line["spans"])
            if not text.strip():
                continue
            y0, y1 = line["bbox"][1], line["bbox"][3]
            if rows:
                top, bottom = rows[-1]["y"]
                if min(bottom, y1) - max(top, y0) > 0.5 * min(bottom - top, y1 - y0):
                    rows[-1]["runs"].append((line["bbox"][0], text))
                    rows[-1]["y"] = (min(top, y0), max(bottom, y1))
                    continue
            rows.append({"y": (y0, y1), "runs": [(line["bbox"][0], text)]})
        out = []
        for row in rows:
            rtl = is_rtl(" ".join(t for _, t in row["runs"]))
            runs = sorted(row["runs"], key=lambda r: -r[0] if rtl else r[0])
            out.append(" ".join(fix_visual_order(t) for _, t in runs))
        return out

    def _text_block(self, block, n, body, page) -> Optional[Block]:
        spans = [s for l in block["lines"] for s in l["spans"] if s["text"].strip()]
        if not spans:
            return None
        rows = self._rows(block["lines"])
        raw = "\n".join(rows)
        chars = sum(len(s["text"].strip()) for s in spans)
        size = sum(s["size"] * len(s["text"].strip()) for s in spans) / max(chars, 1)
        bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
        if _GARBLED.search(raw):
            page.warnings.append("some Arabic text may be garbled (the PDF font has no proper "
                                 "character map)")
        if len(rows) > 1 and sum(bool(_BULLET.match(r)) for r in rows) >= 2:
            items = []
            for row in rows:
                if _BULLET.match(row) or not items:
                    items.append(clean_text(row.lstrip("•●▪◦○■□➢►*-–— ")))
                else:
                    items[-1] = f"{items[-1]} {clean_text(row)}"
            items = [i for i in items if i]
            text = "\n".join(items)
            return Block("list", text, detect_language(text), n, items=items)
        text = clean_text(" ".join(rows))
        if not text:
            return None
        lang = detect_language(text)
        if len(text) <= 200 and len(rows) <= 4 and size >= self.config.heading_ratio * body:
            return Block("heading", text, lang, n, level=1 if size >= 1.6 * body else 2)
        if bold and len(text) <= 100 and len(rows) <= 2 and size >= 1.05 * body \
                and not text.endswith(_END_PUNCT):
            return Block("heading", text, lang, n, level=3)
        return Block("paragraph", text, lang, n)

    # --- page ----------------------------------------------------------------------------
    def _read_page(self, n: int) -> Page:
        fitz = self._fitz
        pdf_page = self._doc.load_page(n - 1)
        page = Page(n, "page")
        area = abs(pdf_page.rect) or 1
        items = []

        tables = []
        if self.config.pdf_tables:
            try:
                tables = list(pdf_page.find_tables().tables)
            except Exception as exc:
                page.warnings.append(f"table detection failed: {exc}")
        boxes = [fitz.Rect(t.bbox) for t in tables]
        for t, box in zip(tables, boxes):
            rows = [[clean_text(fix_visual_order(c or "")) for c in row] for row in t.extract()]
            table = make_table(rows)
            if table:
                text = table_text(table)
                items.append((tuple(box), Block("table", text, detect_language(text), n, table=table)))

        flags = (fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES |
                 fitz.TEXT_MEDIABOX_CLIP | fitz.TEXT_DEHYPHENATE)
        data = pdf_page.get_text("dict", flags=flags)
        blocks = [b for b in data["blocks"] if b.get("type") == 0]
        sizes = [s["size"] for b in blocks for l in b["lines"] for s in l["spans"]
                 for _ in range(len(s["text"].strip()))]
        body = median(sizes) if sizes else 12
        chars = len(sizes)
        for b in blocks:
            center = fitz.Point((b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2)
            if any(center in box for box in boxes):
                continue                      # already read as a table
            # MuPDF can put two columns side by side into one block: split at wide gaps
            lines = [(tuple(l["bbox"]), l) for l in b["lines"]]
            for group in split_columns(lines, gap=max(20.0, 2.0 * body)):   # wider than a bullet indent
                part = {"lines": [l for _, l in group],
                        "bbox": (min(x[0] for x, _ in group), min(x[1] for x, _ in group),
                                 max(x[2] for x, _ in group), max(x[3] for x, _ in group))}
                block = self._text_block(part, n, body, page)
                if block:
                    items.append((part["bbox"], block))

        covered = 0.0
        repeated = self._repeated_images()
        extracted: Dict[int, dict] = {}
        for img in pdf_page.get_images(full=True):
            xref, width, height = img[0], img[2], img[3]
            if xref in repeated or is_decoration(width, height, self.config):
                continue
            for rect in pdf_page.get_image_rects(xref):
                if rect.width < _MIN_DISPLAY or rect.height < _MIN_DISPLAY:
                    continue
                covered += abs(rect & pdf_page.rect)
                if xref not in extracted:
                    try:
                        raw = self._doc.extract_image(xref)
                    except Exception:
                        raw = None
                    if not raw or not raw.get("image"):
                        continue
                    extracted[xref] = self.save_image(raw["image"], raw.get("ext", "png"),
                                                      raw.get("width"), raw.get("height"))
                items.append((tuple(rect), Block("image", "", None, n, image=dict(extracted[xref]))))

        if chars < self.config.ocr_min_chars and covered >= 0.3 * area:
            page.needs_ocr = True             # reported once, by Page.needs_ocr and info.ocr_pages
        rtl = is_rtl(" ".join(blk.text for _, blk in items))
        page.blocks = order_boxes(items, rtl)
        page.warnings = list(dict.fromkeys(page.warnings))
        return page

    # --- document ------------------------------------------------------------------------
    def _title(self, pages) -> str:
        title = clean_text((self._doc.metadata or {}).get("title") or "")
        if title and not _JUNK_TITLE.search(title):
            return title
        return super()._title(pages[:1]) if pages and any(
            b.kind == "heading" for b in pages[0].blocks) else self.path.stem

    def _outline(self, pages) -> List[OutlineEntry]:
        """PDF bookmarks when the file has them, else detected headings (levels 1-2)."""
        toc = self._doc.get_toc(simple=True)
        if toc:
            return [OutlineEntry(clean_text(title), page, level) for level, title, page in toc
                    if level <= 3 and page >= 1 and clean_text(title)]
        out = []
        for e in super()._outline(pages):
            if e.level <= 2 and not (out and out[-1].title == e.title):
                out.append(e)
        return out
