"""Image files (.jpg, .jpeg, .png, .webp) read as a document of one page.

A photo of a paper (camera, WhatsApp, scanner) has no text layer: the page is marked
needs_ocr and its text is read by PageOCR. The orientation stored in EXIF (phones save the
picture sideways and add a "rotate" tag) is applied first, so the page is upright.
"""
import io
from typing import Tuple

from .document import Document
from .errors import CorruptFileError
from .model import Block, Page

FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def upright(blob: bytes) -> Tuple[bytes, str, int, int, bool]:
    """(image bytes, ext, width, height, rotated): the image turned as its EXIF tag says."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(blob)) as im:
        fmt = im.format
        orientation = im.getexif().get(0x0112, 1)
        if orientation in (None, 1):
            return blob, FORMATS.get(fmt, "png"), im.width, im.height, False
        turned = ImageOps.exif_transpose(im)
        out = io.BytesIO()
        if fmt == "JPEG":
            turned.convert("RGB").save(out, "JPEG", quality=92)
        else:
            turned.save(out, "PNG")
        return out.getvalue(), "jpg" if fmt == "JPEG" else "png", turned.width, turned.height, True


class ImageDocument(Document):
    file_type = "image"
    unit_type = "page"

    def __init__(self, path, config):
        super().__init__(path, config)
        try:
            self._blob, self._ext, self._w, self._h, self._rotated = upright(path.read_bytes())
        except Exception as exc:
            raise CorruptFileError(f"Cannot open {path.name} as an image: {exc}") from exc

    @property
    def unit_count(self) -> int:
        return 1

    def _read_page(self, n: int) -> Page:
        page = Page(1, "page", needs_ocr=True)
        image = self.save_image(self._blob, self._ext, self._w, self._h)
        page.blocks = [Block("image", "", None, 1, image=dict(image, page_image=True))]
        if self._rotated:
            page.warnings.append("the photo was turned upright using its EXIF orientation")
        return page

    def _title(self, pages) -> str:
        return self.path.stem

    def page_image(self, n: int, dpi: int = 200) -> Tuple[bytes, str]:
        """The upright image of the page and its MIME type."""
        return self._blob, {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[self._ext]
