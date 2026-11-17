"""PowerPoint (.pptx): one unit per slide; speaker notes become a 'notes' block."""
from collections import Counter
from typing import List, Optional, Set

from .document import Document
from .errors import CorruptFileError
from .images import digest, image_size, is_decoration
from .lang import clean_text, detect_language, is_rtl
from .layout import order_boxes
from .model import Block, OutlineEntry, Page
from .tables import make_table, table_text

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class PptxDocument(Document):
    file_type = "pptx"
    unit_type = "slide"

    def __init__(self, path, config):
        super().__init__(path, config)
        try:
            from pptx import Presentation
            self._prs = Presentation(str(path))
        except Exception as exc:
            raise CorruptFileError(f"Cannot open {path.name} as PowerPoint: {exc}") from exc
        self._slides = list(self._prs.slides)
        self._repeated: Optional[Set[str]] = None

    @property
    def unit_count(self) -> int:
        return len(self._slides)

    # --- pictures ------------------------------------------------------------------------
    @staticmethod
    def _picture_blob(shape):
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        is_picture = shape.shape_type == MSO_SHAPE_TYPE.PICTURE or type(shape).__name__ == "PlaceholderPicture"
        if not is_picture:
            return None
        try:
            return shape.image.blob, shape.image.ext
        except Exception:
            return None

    def _all_pictures(self, shapes):
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from self._all_pictures(shape.shapes)
            else:
                pic = self._picture_blob(shape)
                if pic:
                    yield pic

    def _repeated_images(self) -> Set[str]:
        """Hashes of pictures placed on most slides (logos, backgrounds)."""
        if self._repeated is None:
            counts = Counter()
            for slide in self._slides:
                counts.update({digest(blob) for blob, _ in self._all_pictures(slide.shapes)})
            n = len(self._slides)
            limit = max(3, self.config.repeated_image_ratio * n)
            self._repeated = {h for h, c in counts.items() if n >= 3 and c >= limit}
        return self._repeated

    # --- shapes --------------------------------------------------------------------------
    @staticmethod
    def _placeholder_type(shape) -> str:
        if not shape.is_placeholder:
            return ""
        try:
            kind = shape.placeholder_format.type
            return (getattr(kind, "name", None) or str(kind).split(" ")[0]).upper()
        except Exception:
            return ""

    @staticmethod
    def _has_bullet(paragraph) -> Optional[bool]:
        ppr = paragraph._p.find(f"{A}pPr")
        if ppr is None:
            return None
        if ppr.find(f"{A}buNone") is not None:
            return False
        if ppr.find(f"{A}buChar") is not None or ppr.find(f"{A}buAutoNum") is not None:
            return True
        return None

    def _text_blocks(self, shape, n) -> List[Block]:
        kind = self._placeholder_type(shape)
        if kind in ("FOOTER", "SLIDE_NUMBER", "DATE", "HEADER"):
            return []
        paragraphs = [(clean_text(p.text), p) for p in shape.text_frame.paragraphs]
        paragraphs = [(t, p) for t, p in paragraphs if t]
        if not paragraphs:
            return []
        text = "\n".join(t for t, _ in paragraphs)
        lang = detect_language(text)
        if kind in ("TITLE", "CENTER_TITLE", "VERTICAL_TITLE"):
            return [Block("heading", text.replace("\n", " "), lang, n, "slide", level=1)]
        if kind == "SUBTITLE":
            return [Block("heading", text, lang, n, "slide", level=2)]
        body = kind in ("BODY", "OBJECT", "VERTICAL_BODY", "VERTICAL_OBJECT")
        bullets = [self._has_bullet(p) for _, p in paragraphs]
        bulleted = sum(b is True or (b is None and body) for b in bullets)
        if len(paragraphs) >= 2 and bulleted >= 2:
            items = [t for t, _ in paragraphs]
            return [Block("list", text, lang, n, "slide", items=items)]
        return [Block("paragraph", text, lang, n, "slide")]

    def _shape_blocks(self, shape, n, rtl) -> List[Block]:
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            children = [(self._box(s), self._shape_blocks(s, n, rtl)) for s in shape.shapes]
            return [b for blocks in self._order(children, rtl) for b in blocks]
        if getattr(shape, "has_table", False) and shape.has_table:
            rows = []
            for row in shape.table.rows:
                rows.append([c.text for c in row.cells if not c.is_spanned])
            table = make_table(rows)
            if not table:
                return []
            text = table_text(table)
            return [Block("table", text, detect_language(text), n, "slide", table=table)]
        pic = self._picture_blob(shape)
        if pic:
            blob, ext = pic
            sha = digest(blob)
            width, height = image_size(blob)
            if sha in self._repeated_images() or is_decoration(width, height, self.config):
                return []
            return [Block("image", "", None, n, "slide", image=self.save_image(blob, ext, width, height, sha))]
        if getattr(shape, "has_chart", False) and shape.has_chart:
            self._page_warnings.append("charts are not read")
            return []
        if shape.has_text_frame:
            return self._text_blocks(shape, n)
        return []

    @staticmethod
    def _box(shape):
        if None in (shape.left, shape.top, shape.width, shape.height):
            return None
        return (shape.left, shape.top, shape.left + shape.width, shape.top + shape.height)

    @staticmethod
    def _order(items, rtl):
        placed = [(box, blocks) for box, blocks in items if box is not None and blocks]
        unplaced = [blocks for box, blocks in items if box is None and blocks]
        return order_boxes(placed, rtl, gap=91440 * 0.1) + unplaced   # 0.1 inch in EMU

    def _read_page(self, n: int) -> Page:
        slide = self._slides[n - 1]
        page = Page(n, "slide")
        self._page_warnings = page.warnings
        if slide._element.get("show") in ("0", "false"):
            page.warnings.append("hidden slide")
        shapes = list(slide.shapes)
        rtl = is_rtl(" ".join(s.text_frame.text for s in shapes if s.has_text_frame))
        titles, others = [], []
        for shape in shapes:
            if self._placeholder_type(shape) in ("TITLE", "CENTER_TITLE", "VERTICAL_TITLE"):
                titles.extend(self._shape_blocks(shape, n, rtl))
            else:
                others.append((self._box(shape), self._shape_blocks(shape, n, rtl)))
        page.blocks = titles + [b for blocks in self._order(others, rtl) for b in blocks]
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            notes = clean_text(frame.text) if frame is not None else ""
            if notes:
                page.blocks.append(Block("notes", notes, detect_language(notes), n, "slide"))
        return page

    def _title(self, pages) -> str:
        title = clean_text(self._prs.core_properties.title or "")
        return title or super()._title(pages)

    def _outline(self, pages) -> List[OutlineEntry]:
        """Slide titles; consecutive slides with the same title are one topic."""
        out = []
        for page in pages:
            title = next((b.text for b in page.blocks if b.kind == "heading" and b.level == 1), None)
            if title and (not out or out[-1].title != title):
                out.append(OutlineEntry(title, page.unit, 1))
        return out
