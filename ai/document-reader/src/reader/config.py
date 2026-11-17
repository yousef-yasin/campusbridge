import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

_ROOT = Path(__file__).resolve().parents[2]   # ai/document-reader


@dataclass
class ReaderConfig:
    """Settings, overridable through READER_* environment variables."""
    images_dir: str = str(_ROOT / "extracted-images")   # images saved as <sha256[:16]>.<ext>
    extract_images: bool = True       # False: image blocks are still listed, nothing is written
    min_image_px: int = 48            # smaller width or height = icon / decoration, ignored
    max_image_aspect: float = 12.0    # longer than 12:1 = line / separator, ignored
    repeated_image_ratio: float = 0.6  # same image on >= 60% of pages/slides (3+) = logo, ignored
    pdf_tables: bool = True           # detect tables in PDF pages (slower)
    heading_ratio: float = 1.25       # PDF: font this much larger than body text = heading
    ocr_min_chars: int = 10           # PDF page with fewer text characters has no text layer
    xlsx_preview_rows: int = 20       # rows shown per sheet; the rest are read on request

    @classmethod
    def from_env(cls) -> "ReaderConfig":
        e = os.environ.get
        flag = lambda name, default: e(name, "1" if default else "0").lower() not in ("0", "false", "no")
        try:
            return cls(
                images_dir=e("READER_IMAGES_DIR", cls.images_dir),
                extract_images=flag("READER_EXTRACT_IMAGES", cls.extract_images),
                min_image_px=int(e("READER_MIN_IMAGE_PX", cls.min_image_px)),
                max_image_aspect=float(e("READER_MAX_IMAGE_ASPECT", cls.max_image_aspect)),
                repeated_image_ratio=float(e("READER_REPEATED_IMAGE_RATIO", cls.repeated_image_ratio)),
                pdf_tables=flag("READER_PDF_TABLES", cls.pdf_tables),
                heading_ratio=float(e("READER_HEADING_RATIO", cls.heading_ratio)),
                ocr_min_chars=int(e("READER_OCR_MIN_CHARS", cls.ocr_min_chars)),
                xlsx_preview_rows=int(e("READER_XLSX_PREVIEW_ROWS", cls.xlsx_preview_rows)),
            ).validate()
        except ValueError as exc:
            raise ConfigError(f"Invalid READER_* setting: {exc}") from exc

    def validate(self) -> "ReaderConfig":
        if self.min_image_px < 0 or self.max_image_aspect < 1 or self.xlsx_preview_rows < 0:
            raise ConfigError("min_image_px >= 0, max_image_aspect >= 1, xlsx_preview_rows >= 0")
        if not 0 < self.repeated_image_ratio <= 1:
            raise ConfigError("repeated_image_ratio must be in (0, 1]")
        return self
