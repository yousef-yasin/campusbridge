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
_HEADER_SCAN = 10            # the header is looked for in the first 10 rows
_EXACT_COUNT_LIMIT = 50000   # larger sheets get an estimated row count (no full scan)


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
        self._formulas_wb = None     # second read-only view with formulas, opened only if needed
        if len(self._wb.sheetnames) > len(self._sheets):
            self.warnings.append("chart sheets are not read")

    def close(self) -> None:
        self._wb.close()
        if self._formulas_wb is not None:
            self._formulas_wb.close()

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
                self._charts = sum(1 for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n))
        except Exception:
            self._media = self._charts = 0
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
            scanned = []
            for i, row in enumerate(ws.iter_rows(min_row=1, max_row=_HEADER_SCAN, values_only=True), 1):
                values = [cell_text(v) for v in row]
                while values and not values[-1]:
                    values.pop()
                scanned.append((i, values, sum(1 for v in values if v)))
            # Header: the first row filled across the table (2+ cells and 60% of the fullest
            # row). Rows above it with text (a merged title, a subtitle) are the sheet's title.
            most = max((c for _, _, c in scanned), default=0)
            header = next(((i, v) for i, v, c in scanned if c >= 2 and c >= 0.6 * most), None) or \
                next(((i, v) for i, v, c in scanned if c), None)
            header_row, columns, title = 1, [], None
            if header:
                header_row, values = header
                columns = [v or f"{c + 1}" for c, v in enumerate(values)]
                above = [" ".join(x for x in v if x) for i, v, c in scanned if i < header_row and c]
                title = "\n".join(above) or None
            rows, approximate = 0, False
            if columns:
                estimate = (ws.max_row or 0) - header_row
                if ws.max_row is not None and estimate > _EXACT_COUNT_LIMIT:
                    rows, approximate = estimate, True
                else:                        # non-empty rows inside the table's columns
                    rows = sum(1 for r in ws.iter_rows(min_row=header_row + 1, max_col=len(columns),
                                                       values_only=True)
                               if any(v is not None and str(v).strip() for v in r))
            flags = self._xml.get(ws.title, {})
            self._infos[index] = SheetInfo(ws.title, index, columns, rows, header_row,
                                           flags.get("rtl", False), flags.get("hidden", False),
                                           title, approximate)
        return self._infos[index]

    def _formula_columns(self, info: SheetInfo, preview: int) -> List[str]:
        """Columns whose formulas have no saved result in the preview rows (they read as empty)."""
        try:
            import openpyxl
            if self._formulas_wb is None:
                self._formulas_wb = openpyxl.load_workbook(str(self.path), read_only=True, data_only=False)
            ws_f = self._formulas_wb.worksheets[info.index - 1]
            ws_v = self._sheets[info.index - 1]
            first, last = info.header_row + 1, info.header_row + max(preview, 1)
            width = len(info.columns)
            missing = set()
            for row_f, row_v in zip(ws_f.iter_rows(min_row=first, max_row=last, max_col=width, values_only=True),
                                    ws_v.iter_rows(min_row=first, max_row=last, max_col=width, values_only=True)):
                for col, (f, v) in enumerate(zip(row_f, row_v)):
                    if isinstance(f, str) and f.startswith("=") and v is None:
                        missing.add(col)
            return [info.columns[c] for c in sorted(missing)]
        except Exception:
            return []

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
        if info.title:
            for line in info.title.split("\n"):
                add("paragraph", line)
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
        if info.approximate:
            page.warnings.append(f"row count {info.row_count} is estimated from the sheet size")
        empty = self._formula_columns(info, self.config.xlsx_preview_rows)
        if empty:
            page.warnings.append(
                f"column(s) {', '.join(empty)}: formulas without saved values (the file was not "
                f"saved by Excel after calculating), so these values are empty")
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
        if self._charts:
            many = self._charts != 1
            info.warnings.append(f"{self._charts} chart{'s' if many else ''} in the workbook "
                                 f"{'are' if many else 'is'} not read")
