"""Common document interface, format detection and open_document()."""
import zipfile
from pathlib import Path
from typing import Iterator, List, Optional

from .config import ReaderConfig
from .errors import (CorruptFileError, InputNotFoundError, PageNotFoundError,
                     PasswordProtectedError, UnsupportedFormatError)
from .images import ImageStore
from .lang import detect_language
from .model import Block, DocumentInfo, OutlineEntry, Page

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_LEGACY = {
    "doc": ("Word 97-2003 (.doc)", "Word", "Word Document (*.docx)"),
    "ppt": ("PowerPoint 97-2003 (.ppt)", "PowerPoint", "PowerPoint Presentation (*.pptx)"),
    "xls": ("Excel 97-2003 (.xls)", "Excel", "Excel Workbook (*.xlsx)"),
}
_OLE_STREAMS = {"doc": "WordDocument", "ppt": "PowerPoint Document", "xls": "Workbook"}
_ZIP_MARKERS = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml", "xlsx": "xl/workbook.xml"}


def legacy_error(kind: str) -> UnsupportedFormatError:
    name, app, save_as = _LEGACY[kind]
    return UnsupportedFormatError(
        f"{name} files are not supported. Open the file in {app} and use "
        f"File > Save As > {save_as}, then read the new file.")


def detect_type(path: Path) -> str:
    """'docx', 'pdf', 'pptx', 'xlsx' or 'image' from the file content (the extension is only a hint)."""
    ext = path.suffix.lower().lstrip(".")
    with open(path, "rb") as f:
        head = f.read(12)
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    if head.startswith(_OLE):
        data = path.read_bytes()
        if "EncryptedPackage".encode("utf-16-le") in data:
            raise PasswordProtectedError(f"{path.name} is password protected; remove the password "
                                         f"in Office (File > Info > Protect) and save again")
        for kind, stream in _OLE_STREAMS.items():
            if stream.encode("utf-16-le") in data:
                raise legacy_error(kind)
        if ext in _LEGACY:
            raise legacy_error(ext)
        raise UnsupportedFormatError(f"{path.name} is an old binary Office file that is not supported")
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile as exc:
            raise CorruptFileError(f"{path.name} is damaged (bad zip): {exc}") from exc
        for kind, marker in _ZIP_MARKERS.items():
            if marker in names:
                return kind
        raise UnsupportedFormatError(f"{path.name} is a zip file but not a Word, PowerPoint or Excel document")
    if ext in _LEGACY:
        raise legacy_error(ext)
    raise UnsupportedFormatError(
        f"{path.name}: unsupported file type (supported: .docx, .pdf, .pptx, .xlsx, "
        f".jpg, .jpeg, .png, .webp)")


class Document:
    """A document opened for reading. Pages are processed only when asked for.

    page(n) reads one page, slide or sheet; info scans the whole document once (cached).
    """
    file_type = ""
    unit_type = "page"

    def __init__(self, path: Path, config: ReaderConfig):
        self.path = path
        self.config = config
        self.store = ImageStore(config)
        self._collect_only = False    # True while info is computed: images are not written
        self._info: Optional[DocumentInfo] = None
        self.warnings: List[str] = []

    # --- to implement per format -----------------------------------------------------------
    @property
    def unit_count(self) -> int:
        raise NotImplementedError

    def _read_page(self, n: int) -> Page:
        raise NotImplementedError

    def _title(self, pages: List[Page]) -> str:
        for page in pages:
            for block in page.blocks:
                if block.kind == "heading" and block.text:
                    return block.text.split("\n")[0]
        return self.path.stem

    def _outline(self, pages: List[Page]) -> List[OutlineEntry]:
        return [OutlineEntry(b.text.replace("\n", " "), b.unit, b.level or 1, b.sheet)
                for p in pages for b in p.blocks if b.kind == "heading" and (b.level or 1) <= 3]

    def close(self) -> None:
        pass

    def page_image(self, n: int, dpi: int = 200):
        """(image bytes, MIME type) of the whole page, for OCR. PDF pages and image files only."""
        raise NotImplementedError(f"{self.file_type} pages have no page image")

    # --- common ---------------------------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def save_image(self, blob: bytes, ext: str, width=None, height=None, sha=None):
        if self._collect_only:
            from .images import digest
            return {"sha256": sha or digest(blob), "ext": ext, "width": width, "height": height,
                    "description": ""}
        return self.store.save(blob, ext, width, height, sha)

    def page(self, n: int) -> Page:
        """One page / slide / sheet (1-based), without reading the others."""
        if not isinstance(n, int) or not 1 <= n <= self.unit_count:
            raise PageNotFoundError(
                f"{self.unit_type} {n} does not exist ({self.path.name} has {self.unit_count})")
        from .references import mark_references
        return mark_references(self._read_page(n))

    def pages(self) -> Iterator[Page]:
        for n in range(1, self.unit_count + 1):
            yield self.page(n)

    def blocks(self) -> List[Block]:
        return [b for p in self.pages() for b in p.blocks]

    @property
    def info(self) -> DocumentInfo:
        if self._info is None:
            self._collect_only = True
            try:
                pages = list(self.pages())
            finally:
                self._collect_only = False
            blocks = [b for p in pages for b in p.blocks]
            warnings = list(self.warnings)
            for p in pages:
                warnings.extend(f"{p.label}: {w}" for w in p.warnings)
            ocr = [p.unit for p in pages if p.needs_ocr]
            if ocr:
                warnings.insert(0, f"{len(ocr)} of {len(pages)} pages have no text layer "
                                   f"(scanned): OCR is needed for pages {_ranges(ocr)}")
            self._info = DocumentInfo(
                title=self._title(pages), file_type=self.file_type, unit_type=self.unit_type,
                unit_count=self.unit_count,
                image_count=sum(b.kind == "image" for b in blocks),
                table_count=sum(b.kind == "table" for b in blocks),
                chart_count=sum(b.kind == "chart" for b in blocks),
                language=detect_language(" ".join(b.text for b in blocks if b.kind != "image")),
                outline=self._outline(pages), needs_ocr=bool(ocr), ocr_pages=ocr,
                warnings=list(dict.fromkeys(warnings)))
            self._extend_info(self._info, pages)
        return self._info

    def _extend_info(self, info: DocumentInfo, pages: List[Page]) -> None:
        pass


def _ranges(numbers: List[int]) -> str:
    out, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            out.append(str(start) if start == n else f"{start}-{n}")
            start = None
    return ", ".join(out)


def open_document(path, config: Optional[ReaderConfig] = None) -> Document:
    """Open a .docx, .pdf, .pptx, .xlsx or image file. Raises a ReaderError subclass on failure."""
    config = (config or ReaderConfig.from_env()).validate()
    path = Path(path)
    if not path.is_file():
        raise InputNotFoundError(f"File not found: {path}")
    if path.stat().st_size == 0:
        raise InputNotFoundError(f"File is empty: {path}")
    kind = detect_type(path)
    if kind == "docx":
        from .docx_reader import DocxDocument as cls
    elif kind == "pdf":
        from .pdf_reader import PdfDocument as cls
    elif kind == "pptx":
        from .pptx_reader import PptxDocument as cls
    elif kind == "image":
        from .image_reader import ImageDocument as cls
    else:
        from .xlsx_reader import XlsxDocument as cls
    doc = cls(path, config)
    ext = path.suffix.lower().lstrip(".")
    if ext != kind and not (kind == "image" and ext in ("jpg", "jpeg", "png", "webp")):
        doc.warnings.append(f"file extension is .{ext} but the content is {kind}")
    return doc
