"""Image filtering and storage by content hash."""
import hashlib
import io
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import ReaderConfig

log = logging.getLogger(__name__)

_EXT = {"jpeg": "jpg", "jpe": "jpg", "tif": "tiff", "x-wmf": "wmf", "x-emf": "emf"}


def image_size(blob: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Pixel size from the image header; (None, None) when Pillow cannot read it (EMF/WMF)."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(blob)) as im:
            return im.size
    except Exception:
        return None, None


def is_decoration(width: Optional[int], height: Optional[int], config: ReaderConfig) -> bool:
    """Icons, bullets and separator lines."""
    if not width or not height:
        return False                      # unknown size (vector formats): keep
    if min(width, height) < config.min_image_px:
        return True
    return max(width, height) / min(width, height) > config.max_image_aspect


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class ImageStore:
    """Saves images as <images_dir>/<sha256[:16]>.<ext>; identical images are stored once."""

    def __init__(self, config: ReaderConfig):
        self.config = config
        self.directory = Path(config.images_dir)

    def save(self, blob: bytes, ext: str, width=None, height=None, sha=None) -> Dict:
        ext = (ext or "bin").lower().lstrip(".")
        ext = _EXT.get(ext, ext)
        sha = sha or digest(blob)
        if width is None:
            width, height = image_size(blob)
        info = {"sha256": sha, "ext": ext, "width": width, "height": height, "description": ""}
        if self.config.extract_images:
            path = self.directory / f"{sha[:16]}.{ext}"
            try:
                if not path.exists():
                    self.directory.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(blob)
                info["path"] = str(path)
            except OSError as exc:
                log.warning("Image not saved: %s", exc)
        return info
