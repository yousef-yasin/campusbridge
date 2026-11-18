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
    # --- phase 2: image descriptions (Gemini vision; images are sent to Google) ---
    vision_model: str = "gemini-3.5-flash-lite"   # free tier; gemini-4-hydrogen is stronger but was overloaded (503)
    vision_max_images: int = 20       # API calls per run (cached descriptions do not count)
    vision_timeout: int = 120         # seconds per request
    vision_retry_wait: int = 30       # on 429, wait up to this long once, then stop
    vision_thinking: str = "low"      # Gemini thinking level ("" = model default)
    descriptions_dir: str = str(_ROOT / "image-descriptions")   # reviewable JSON cache
    env_file: str = str(_ROOT / ".env")                          # holds GEMINI_API_KEY

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
                vision_model=e("READER_VISION_MODEL", cls.vision_model),
                vision_max_images=int(e("READER_VISION_MAX_IMAGES", cls.vision_max_images)),
                vision_timeout=int(e("READER_VISION_TIMEOUT", cls.vision_timeout)),
                vision_retry_wait=int(e("READER_VISION_RETRY_WAIT", cls.vision_retry_wait)),
                vision_thinking=e("READER_VISION_THINKING", cls.vision_thinking),
                descriptions_dir=e("READER_DESCRIPTIONS_DIR", cls.descriptions_dir),
                env_file=e("READER_ENV_FILE", cls.env_file),
            ).validate()
        except ValueError as exc:
            raise ConfigError(f"Invalid READER_* setting: {exc}") from exc

    def validate(self) -> "ReaderConfig":
        if self.min_image_px < 0 or self.max_image_aspect < 1 or self.xlsx_preview_rows < 0:
            raise ConfigError("min_image_px >= 0, max_image_aspect >= 1, xlsx_preview_rows >= 0")
        if not 0 < self.repeated_image_ratio <= 1:
            raise ConfigError("repeated_image_ratio must be in (0, 1]")
        if self.vision_max_images < 0 or not self.vision_model.strip():
            raise ConfigError("vision_max_images >= 0 and vision_model must not be empty")
        return self
