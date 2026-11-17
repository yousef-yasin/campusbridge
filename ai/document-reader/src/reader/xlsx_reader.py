"""Excel (.xlsx): one unit per sheet. Only a preview is read; rows() reads more on request."""
import re
import zipfile
from typing import Dict, Iterator, List, Optional
from xml.etree import ElementTree as ET

from .document import Document
from .errors import CorruptFileError, PageNotFoundError
from .lang import detect_language, is_rtl
from .model import Block, OutlineEntry, Page, SheetInfo
from .tables import cell_text, make_table, table_text

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
_HEADER_SCAN = 10    # the header is the first non-empty row among the first 10


class XlsxDocument(Document):
    file_type = "xlsx"
    unit_type = "sheet"

    def __init__(self, path, config):
        super().__init__(path, config)
        try:
            import openpyxl
            self._wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        except Exception as exc:
            raise CorruptFileError(f"Cannot open {path.name} as Excel: {exc}") from exc
        self._sheets = list(self._wb.worksheets)       # chart sheets are not included
        self._xml = self._sheet_xml_flags()
        self._infos: Dict[int, SheetInfo] = {}
        if len(self._wb.sheetnames) > len(self._sheets):
            self.warnings.append("chart sheets are not read")

    def close(self) -> None:
        self._wb.close()

    @property
    def unit_count(self) -> int:
        return len(self._sheets)

    def _sheet_xml_flags(self) -> Dict[str, Dict[str, bool]]:
        """Per sheet name: right-to-left view and hidden state, read from the workbook XML."""
        flags = {}
        try:
            with zipfile.ZipFile(self.path) as z:
                book = ET.fromstring(z.read("xl/workbook.xml"))
                rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                targets = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", _NS)}
                for s in book.findall("m:sheets/m:sheet", _NS):
                    target = targets.get(s.get(f"{{{_NS['r']}}}id"), "")
                    target = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                    head = ""
                    if target in z.namelist():
                        with z.open(target) as f:
                            head = f.read(4096).decode("utf-8", "ignore")
                    flags[s.get("name")] = {"rtl": bool(re.search(r'rightToLeft="(1|true)"', head)),
                                            "hidden": s.get("state") in ("hidden", "veryHidden")}
                self._media = sum(1 for n in z.namelist() if n.startswith("xl/media/"))
        except Exception:
            self._media = 0
        return flags

    def _ws(self, ref):
        if isinstance(ref, int):
            if not 1 <= ref <= len(self._sheets):
                raise PageNotFoundError(f"sheet {ref} does not exist ({len(self._sheets)} sheets)")
            return ref, self._sheets[ref - 1]
        for i, ws in enumerate(self._sheets, 1):
            if ws.title == ref:
                return i, ws
        raise PageNotFoundError(f"no sheet named '{ref}' (sheets: {', '.join(self._wb.sheetnames)})")

    def sheet_info(self, ref) -> SheetInfo:
        """Name, column names and row count of one sheet (reads the header rows only)."""
        index, ws = self._ws(ref)
        if index not in self._infos:
            header_row, columns = 1, []
            for i, row in enumerate(ws.iter_rows(min_row=1, max_row=_HEADER_SCAN, values_only=True), 1):
                values = [cell_text(v) for v in row]
                if any(values):
                    header_row = i
                    while values and not values[-1]:
                        values.pop()
                    columns = [v or f"{c + 1}" for c, v in enumerate(values)]
                    break
            max_row = ws.max_row
            if max_row is None:              # no saved dimension: count rows (this sheet only)
                max_row = sum(1 for _ in ws.iter_rows(values_only=True))
            rows = max(0, max_row - header_row) if columns else 0
            flags = self._xml.get(ws.title, {})
            self._infos[index] = SheetInfo(ws.title, index, columns, rows, header_row,
                                           flags.get("rtl", False), flags.get("hidden", False))
        return self._infos[index]

    def page(self, ref) -> Page:
        """A sheet by 1-based index or by name."""
        if isinstance(ref, str):
            ref = self._ws(ref)[0]
        return super().page(ref)

    def rows(self, ref, start: int = 1, count: int = 50) -> Iterator[Dict[str, str]]:
        """Data rows start..start+count-1 (1 = first row after the header), as {column: value}.

        Rows are streamed from the file; nothing else in the sheet is read.
        """
        info = self.sheet_info(ref)
        _, ws = self._ws(ref)
        first = info.header_row + max(1, start)
        last = first + max(0, count) - 1
        if count <= 0 or not info.columns:
            return
        for row in ws.iter_rows(min_row=first, max_row=last, max_col=len(info.columns), values_only=True):
            values = [cell_text(v) for v in row]
            if any(values):
                yield dict(zip(info.columns, values + [""] * (len(info.columns) - len(values))))

    def _read_page(self, n: int) -> Page:
        info = self.sheet_info(n)
        page = Page(n, "sheet", sheet=info.name)
        add = lambda kind, text, **kw: page.blocks.append(
            Block(kind, text, detect_language(text), n, "sheet", info.name, **kw))
        add("heading", info.name, level=1)
        if info.hidden:
            page.warnings.append("hidden sheet")
        if not info.columns:
            add("paragraph", "Empty sheet" if not is_rtl(info.name) else "ورقة فارغة")
            return page
        arabic = is_rtl(" ".join([info.name] + info.columns))
        cols = ("، " if arabic else ", ").join(info.columns)
        rows, ncols = info.row_count, len(info.columns)
        summary = (f"عدد الصفوف {rows}، وعدد الأعمدة {ncols}: {cols}" if arabic else
                   f"{rows} row{'s' * (rows != 1)}, {ncols} column{'s' * (ncols != 1)}: {cols}")
        add("paragraph", summary)
        preview = [list(r.values()) for r in self.rows(n, 1, self.config.xlsx_preview_rows)]
        table = make_table([info.columns] + preview, total_rows=info.row_count)
        if table:
            table["columns"] = info.columns
            add("table", table_text(table), table=table)
        if info.row_count > len(preview):
            page.warnings.append(f"showing {len(preview)} of {info.row_count} rows; "
                                 f"use rows() / --rows for more")
        return page

    def _title(self, pages) -> str:
        return (self._wb.properties.title or "").strip() or self.path.stem

    def _outline(self, pages) -> List[OutlineEntry]:
        return [OutlineEntry(p.sheet, p.unit, 1, p.sheet) for p in pages]

    def _extend_info(self, info, pages) -> None:
        info.sheets = [self.sheet_info(p.unit) for p in pages]
        info.image_count = self._media
        info.table_count = sum(1 for s in info.sheets if s.columns)
        info.warnings = [w for w in info.warnings if "showing" not in w]
        if self._media:
            info.warnings.append(f"{self._media} images in the workbook are counted but not extracted")
