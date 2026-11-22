"""Word (.docx). Page numbers come from the page breaks Word saved in the file."""
import re
from typing import List, Optional

from .document import Document
from .errors import CorruptFileError
from .images import image_size, is_decoration
from .lang import clean_text, detect_language
from .model import Block, OutlineEntry, Page
from .tables import table_blocks

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_HEADING = re.compile(r"^(?:heading|عنوان)\s*(\d)$", re.I)
_END_PUNCT = tuple(".:؛;؟?!،,")


class DocxDocument(Document):
    file_type = "docx"
    unit_type = "page"

    def __init__(self, path, config):
        super().__init__(path, config)
        try:
            import docx
            self._doc = docx.Document(str(path))
        except Exception as exc:
            raise CorruptFileError(f"Cannot open {path.name} as Word: {exc}") from exc
        self._body = self._doc.element.body
        self._rendered = bool(self._body.findall(f".//{W}lastRenderedPageBreak"))
        self._elements = list(self._walk(self._body))
        self._starts = self._page_starts()
        self._has_styled_headings = any(self._style_level(e) for e in self._elements if e.tag == f"{W}p")
        if self._body.findall(f".//{W}txbxContent"):
            self.warnings.append("text inside text boxes is not read")
        if len(self._elements) > 1 and self.unit_count == 1 and not self._rendered:
            self.warnings.append("this file has no saved page breaks (not saved by Word): "
                                 "all content is reported as page 1")

    # --- structure -------------------------------------------------------------------------
    def _walk(self, parent):
        for child in parent:
            if child.tag in (f"{W}p", f"{W}tbl"):
                yield child
            elif child.tag == f"{W}sdt":
                content = child.find(f"{W}sdtContent")
                if content is not None:
                    yield from self._walk(content)

    def _breaks(self, element):
        """(breaks before the element's content, breaks after it)."""
        before = after = 0
        seen_text = False
        for node in element.iter():
            if node.tag == f"{W}t" and (node.text or "").strip():
                seen_text = True
            is_break = (node.tag == f"{W}lastRenderedPageBreak") if self._rendered else \
                (node.tag == f"{W}br" and node.get(f"{W}type") == "page")
            if is_break:
                if seen_text or element.tag == f"{W}tbl":
                    after += 1
                else:
                    before += 1
        if not self._rendered and element.tag == f"{W}p":
            ppr = element.find(f"{W}pPr")
            if ppr is not None:
                pbb = ppr.find(f"{W}pageBreakBefore")
                if pbb is not None and pbb.get(f"{W}val", "1") not in ("0", "false"):
                    before += 1
                sect = ppr.find(f"{W}sectPr")
                if sect is not None:
                    kind = sect.find(f"{W}type")
                    if kind is None or kind.get(f"{W}val") in ("nextPage", "evenPage", "oddPage"):
                        after += 1
        return before, after

    def _page_starts(self) -> List[int]:
        """Page number on which each body element starts."""
        page, starts = 1, []
        for element in self._elements:
            before, after = self._breaks(element)
            page += before
            starts.append(page)
            page += after
        return starts

    @property
    def unit_count(self) -> int:
        return max(self._starts or [1])

    # --- styles ----------------------------------------------------------------------------
    def _paragraph(self, element):
        from docx.text.paragraph import Paragraph
        return Paragraph(element, self._doc._body)

    def _style_level(self, element) -> Optional[int]:
        ppr = element.find(f"{W}pPr")
        if ppr is not None:
            lvl = ppr.find(f"{W}outlineLvl")
            if lvl is not None and lvl.get(f"{W}val", "9").isdigit() and int(lvl.get(f"{W}val")) < 9:
                return int(lvl.get(f"{W}val")) + 1
        try:
            style = self._paragraph(element).style
        except Exception:
            return None
        depth = 0
        while style is not None and depth < 10:
            name = (style.name or "").strip()
            if name.lower() in ("title", "العنوان"):
                return 1
            match = _HEADING.match(name)
            if match:
                return int(match.group(1))
            spr = style.element.find(f"{W}pPr")
            lvl = spr.find(f"{W}outlineLvl") if spr is not None else None
            if lvl is not None and lvl.get(f"{W}val", "9").isdigit() and int(lvl.get(f"{W}val")) < 9:
                return int(lvl.get(f"{W}val")) + 1
            style, depth = style.base_style, depth + 1
        return None

    def _is_list(self, element, paragraph) -> bool:
        ppr = element.find(f"{W}pPr")
        if ppr is not None and ppr.find(f"{W}numPr") is not None:
            return True
        try:
            name = (paragraph.style.name or "").lower()
        except Exception:
            name = ""
        return name.startswith("list") and name != "list paragraph"   # List Bullet, List Number

    @staticmethod
    def _all_bold(paragraph) -> bool:
        runs = [r for r in paragraph.runs if r.text.strip()]
        return bool(runs) and all(r.bold or (r.style is not None and r.style.font.bold) for r in runs)

    # --- content ---------------------------------------------------------------------------
    def _images(self, element, unit) -> List[Block]:
        blocks = []
        rel_ids = [n.get(R_EMBED) for n in element.iter(A_BLIP)] + \
                  [n.get(R_ID) for n in element.iter(V_IMAGEDATA)]
        for rid in filter(None, rel_ids):
            part = self._doc.part.related_parts.get(rid)
            blob = getattr(part, "blob", None)
            if not blob:
                continue
            width, height = image_size(blob)
            if is_decoration(width, height, self.config):
                continue
            ext = str(part.partname).rsplit(".", 1)[-1]
            image = self.save_image(blob, ext, width, height)
            blocks.append(Block("image", "", None, unit, image=image))
        return blocks

    def _read_page(self, n: int) -> Page:
        page = Page(n, "page")
        pending_list: List[str] = []

        def flush():
            if pending_list:
                text = "\n".join(pending_list)
                page.blocks.append(Block("list", text, detect_language(text), n, items=list(pending_list)))
                pending_list.clear()

        for element, start in zip(self._elements, self._starts):
            if start != n:
                if start > n:
                    break
                continue
            if element.tag == f"{W}tbl":
                flush()
                page.blocks.extend(self._table(element, n))
                if element.findall(f".//{A_BLIP}"):
                    page.warnings.append("images inside tables are not read")
                continue
            paragraph = self._paragraph(element)
            text = clean_text(paragraph.text)
            images = self._images(element, n)
            if text:
                level = self._style_level(element)
                if level is None and not self._has_styled_headings and len(text) <= 80 \
                        and not text.endswith(_END_PUNCT) and self._all_bold(paragraph):
                    level = 3
                if level is not None:
                    flush()
                    page.blocks.append(Block("heading", text, detect_language(text), n, level=level))
                elif self._is_list(element, paragraph):
                    pending_list.append(text)
                else:
                    flush()
                    page.blocks.append(Block("paragraph", text, detect_language(text), n))
            if images:
                flush()
                page.blocks.extend(images)
        flush()
        return page

    def _table(self, element, unit) -> List[Block]:
        from docx.table import Table
        try:
            rows = []
            for row in Table(element, self._doc._body).rows:
                seen, cells = set(), []
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(cell.text)
                rows.append(cells)
        except Exception:
            return []
        return table_blocks(rows, unit)

    def _title(self, pages) -> str:
        title = clean_text(self._doc.core_properties.title or "")
        return title or super()._title(pages)

    def _outline(self, pages) -> List[OutlineEntry]:
        limit = 2 if self._has_styled_headings else 3
        return [e for e in super()._outline(pages) if e.level <= limit]
