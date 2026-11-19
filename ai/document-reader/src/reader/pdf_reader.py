"""PDF with a text layer (PyMuPDF). Scanned pages are reported as needing OCR.

All PyMuPDF use is in this file, so the PDF library can be replaced without touching the rest.
"""
import re
from collections import Counter
from statistics import median
from typing import Dict, List, Optional, Set

from .document import Document, _ranges
from .errors import CorruptFileError, PasswordProtectedError
from .images import is_decoration
from .lang import (clean_text, detect_language, fix_leading_marks, fix_visual_order, is_rtl,
                   looks_reversed)
from .layout import order_boxes, split_columns
from .model import Block, OutlineEntry, Page
from .tables import table_blocks

_BULLET_CHARS = "•●▪◦○■□➢►*-–—"
_BULLET = re.compile(r"^\s*(?:[•●▪◦○■□➢►–—\-*-]"
                     r"|\(?[0-9٠-٩]{1,2}[.)\-]\s)")
_JUNK_TITLE = re.compile(r"^(microsoft (word|powerpoint)\s*-|powerpoint presentation|untitled|"
                         r"presentation\d*$|document\d*$)|\.(docx?|pptx?|pdf)$|[0-9a-f]{16,}", re.I)
_GARBLED = re.compile("[ء-ي][ƀ-ɏ]|[ƀ-ɏ][ء-ي]")
_MIN_DISPLAY = 20        # points: images drawn smaller than this are icons
_BACKGROUND = 0.8        # an image over 80% of the page with the page's text on top = background
_BODY_SAMPLE = 10        # pages sampled for the document's body font size
_END_PUNCT = tuple(".:؛;؟?!،,")
_SENTENCE_END = tuple(".!?؟:؛…")
_REVERSED = ("Arabic text on this page looks reversed (stored letter by letter in visual "
             "order) and could not be repaired; check the page or use OCR")


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
        self._body: Optional[float] = None
        self._background_pages: Set[int] = set()

    def close(self) -> None:
        self._doc.close()

    def page_image(self, n: int, dpi: int = 200):
        """The page rendered as PNG at dpi (for OCR)."""
        pix = self._doc.load_page(n - 1).get_pixmap(dpi=dpi, alpha=False)
        return pix.tobytes("png"), "image/png"

    @property
    def unit_count(self) -> int:
        return self._doc.page_count

    @property
    def _flags(self):
        f = self._fitz
        return f.TEXT_PRESERVE_WHITESPACE | f.TEXT_PRESERVE_LIGATURES | f.TEXT_MEDIABOX_CLIP | f.TEXT_DEHYPHENATE

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

    def _body_size(self) -> float:
        """Body font size of the whole document (median character size over up to 10 pages).

        Judging headings per page fails on slide-like pages with two lines of text; one size for
        the document also keeps heading levels consistent. Computed once, from text only.
        """
        if self._body is None:
            n = self._doc.page_count
            k = min(n, _BODY_SAMPLE)
            picks = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
            sizes = []
            for i in picks:
                data = self._doc.load_page(i).get_text("dict", flags=self._flags)
                sizes.extend(s["size"] for b in data["blocks"] if b.get("type") == 0
                             for l in b["lines"] for s in l["spans"] for _ in range(len(s["text"].strip())))
            self._body = median(sizes) if sizes else 12.0
        return self._body

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

    def _text_block(self, block, n, body, page):
        """(Block, average font size) for one MuPDF text block, or None."""
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
                    items.append(clean_text(row.lstrip(_BULLET_CHARS + " ")))
                else:
                    items[-1] = f"{items[-1]} {clean_text(row)}"
            items = [i for i in items if i]
            text = "\n".join(items)
            return Block("list", text, detect_language(text), n, items=items), size
        text = clean_text(" ".join(rows))
        if not text:
            return None
        lang = detect_language(text)
        if len(text) <= 200 and len(rows) <= 4 and size >= self.config.heading_ratio * body:
            return Block("heading", text, lang, n, level=1 if size >= 1.6 * body else 2), size
        if bold and len(text) <= 100 and len(rows) <= 2 and size >= 1.05 * body \
                and not text.endswith(_END_PUNCT):
            return Block("heading", text, lang, n, level=3), size
        return Block("paragraph", text, lang, n), size

    # --- tables --------------------------------------------------------------------------
    def _find_tables(self, pdf_page, page):
        """Tables from PyMuPDF's layout model plus ruled tables it misses.

        The layout model (default in PyMuPDF 2.x) finds tables without ruling lines, but drops
        some ruled tables, for example ones with only Arabic text.
        """
        Rect = self._fitz.Rect
        ruled, layout = [], []
        try:
            ruled = list(pdf_page.find_tables(use_layout=False).tables)   # exact grid from lines
        except TypeError:
            pass                                       # PyMuPDF without the layout option
        except Exception as exc:
            page.warnings.append(f"ruled table detection failed: {exc}")
        try:
            layout = list(pdf_page.find_tables().tables)
        except Exception as exc:
            page.warnings.append(f"table detection failed: {exc}")

        def same(a, b):                                # the two finders saw the same table
            a, b = Rect(a.bbox), Rect(b.bbox)
            return abs(a & b) > 0.5 * min(abs(a), abs(b))
        return ruled + [t for t in layout if not any(same(t, r) for r in ruled)]

    def _cell_text(self, pdf_page, rect) -> str:
        """Cell text through the normal text engine: Table.extract() orders characters left to
        right, which reverses Arabic."""
        if rect is None:
            return ""
        data = pdf_page.get_text("dict", clip=self._fitz.Rect(rect), flags=self._flags)
        lines = [l for b in data["blocks"] if b.get("type") == 0 for l in b["lines"]]
        return "\n".join(clean_text(r) for r in self._rows(lines))

    def _table_items(self, pdf_page, page, n):
        items, boxes = [], []
        for table in self._find_tables(pdf_page, page):
            rows = [[self._cell_text(pdf_page, c) for c in row.cells] for row in table.rows]
            if is_rtl(" ".join(c for row in rows for c in row)):
                rows = [row[::-1] for row in rows]     # first column is the rightmost one
            box = self._fitz.Rect(table.bbox)
            boxes.append(box)
            for block in table_blocks(rows, n):
                items.append((tuple(box), block))
        return items, boxes

    # --- page ----------------------------------------------------------------------------
    def _read_page(self, n: int) -> Page:
        fitz = self._fitz
        pdf_page = self._doc.load_page(n - 1)
        page = Page(n, "page")
        area = abs(pdf_page.rect) or 1
        sizes: Dict[int, tuple] = {}     # id(block) -> (bbox, font size), for joining wrapped lines
        items, boxes = self._table_items(pdf_page, page, n) if self.config.pdf_tables else ([], [])

        body = self._body_size()
        data = pdf_page.get_text("dict", flags=self._flags)
        blocks = [b for b in data["blocks"] if b.get("type") == 0]
        chars = sum(len(s["text"].strip()) for b in blocks for l in b["lines"] for s in l["spans"])
        text_centers = [(fitz.Point((b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2),
                         sum(len(s["text"].strip()) for l in b["lines"] for s in l["spans"])) for b in blocks]
        for b in blocks:
            center = fitz.Point((b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2)
            if any(center in box for box in boxes):
                continue                      # already read as a table
            # MuPDF can put two columns side by side into one block: split at wide gaps
            lines = [(tuple(l["bbox"]), l) for l in b["lines"]]
            for group in split_columns(lines, gap=max(20.0, 2.0 * body)):   # wider than a bullet indent
                bbox = (min(x[0] for x, _ in group), min(x[1] for x, _ in group),
                        max(x[2] for x, _ in group), max(x[3] for x, _ in group))
                result = self._text_block({"lines": [l for _, l in group], "bbox": bbox}, n, body, page)
                if result:
                    block, size = result
                    sizes[id(block)] = (bbox, size)
                    items.append((bbox, block))

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
                shown = abs(rect & pdf_page.rect)
                if shown >= _BACKGROUND * area and chars >= self.config.ocr_min_chars:
                    on_top = sum(c for center, c in text_centers if center in rect)
                    if on_top >= 0.5 * chars:              # the page's text is drawn over it
                        self._background_pages.add(n)
                        continue
                covered += shown
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
            for rect, blk in items:           # the scan itself: replaced by its text after OCR
                if blk.kind == "image" and abs(self._fitz.Rect(rect) & pdf_page.rect) >= 0.3 * area:
                    blk.image["covers_page"] = True
        rtl = is_rtl(" ".join(blk.text for _, blk in items))
        page.blocks = self._join_wrapped(order_boxes(items, rtl), sizes, n)
        for block in page.blocks:
            if block.kind in ("heading", "paragraph"):
                block.text = fix_leading_marks(block.text)
        if looks_reversed(" ".join(b.text for b in page.blocks if b.kind != "image")):
            page.warnings.append(_REVERSED)
        page.warnings = list(dict.fromkeys(page.warnings))
        return page

    @staticmethod
    def _join_wrapped(blocks: List[Block], sizes, n) -> List[Block]:
        """Join a sentence that the PDF wrote as separate blocks, one per line.

        Two paragraphs are joined when they have the same font size, touch vertically, are
        aligned on the reading side (right for Arabic), and the first one does not end a sentence.
        """
        out: List[Block] = []
        for block in blocks:
            prev = out[-1] if out else None
            if prev is not None and prev.kind == block.kind == "paragraph" \
                    and id(prev) in sizes and id(block) in sizes:
                (pb, ps), (nb, ns) = sizes[id(prev)], sizes[id(block)]
                size = max(ps, ns)
                gap = nb[1] - pb[3]                      # negative: the line boxes overlap
                overlap = -gap if gap < 0 else 0
                next_line = nb[1] > pb[1] and overlap < 0.5 * min(pb[3] - pb[1], nb[3] - nb[1])
                rtl = is_rtl(f"{prev.text} {block.text}")
                aligned = abs(pb[2] - nb[2]) <= 2 * size if rtl else abs(pb[0] - nb[0]) <= 2 * size
                # wrapped lines touch; list items and separate lines have visible space between them
                if abs(ps - ns) <= 0.1 * size and next_line and gap <= 0.35 * size \
                        and min(pb[2], nb[2]) > max(pb[0], nb[0]) and aligned \
                        and not prev.text.endswith(_SENTENCE_END):
                    text = f"{prev.text} {block.text}"
                    merged = Block("paragraph", text, detect_language(text), n)
                    sizes[id(merged)] = ((min(pb[0], nb[0]), pb[1], max(pb[2], nb[2]), nb[3]), size)
                    out[-1] = merged
                    continue
            out.append(block)
        return out

    # --- document ------------------------------------------------------------------------
    def _title(self, pages) -> str:
        """Metadata title unless it is a file name or tool default; else page 1's main headings."""
        title = clean_text((self._doc.metadata or {}).get("title") or "")
        if title and title != self.path.stem and not _JUNK_TITLE.search(title):
            return title
        heads = [b.text for b in (pages[0].blocks if pages else [])
                 if b.kind == "heading" and (b.level or 3) <= 2][:2]
        if heads:
            joined = " - ".join(heads)
            return joined if len(joined) <= 150 else heads[0]
        return self.path.stem

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

    def _extend_info(self, info, pages) -> None:
        if self._background_pages:
            info.warnings.append(f"full-page background images skipped on pages "
                                 f"{_ranges(sorted(self._background_pages))}")
