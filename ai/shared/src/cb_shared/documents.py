"""A lecture file -> text units, through document-reader (used by the CLIs of the AI modules)."""
from typing import Iterable, List, Optional, Tuple

from .paths import use_module
from .units import TextUnit, from_pages


def parse_pages(spec: Optional[str]) -> Optional[set]:
    """'7,16' or '1-3,9' -> {7, 16} / {1, 2, 3, 9}; None for all pages."""
    if not spec:
        return None
    wanted = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        wanted.update(range(int(a), int(b or a) + 1))
    return wanted


def load_units(path, pages: Optional[Iterable[int]] = None, ocr: bool = False, describe: bool = False,
               language: Optional[str] = None) -> Tuple[List[TextUnit], str, List[str]]:
    """(units of the wanted pages, file title, warnings).

    Image descriptions already in document-reader's cache are used (no network). describe=True
    describes the other images of those pages, and ocr=True reads scanned pages and photos:
    both send content to Google.
    """
    use_module("document-reader")
    from reader import ImageDescriber, PageOCR, open_document
    wanted = set(pages) if pages is not None else None
    warnings: List[str] = []
    with open_document(path) as doc:
        numbers = range(1, doc.unit_count + 1)
        chosen = [doc.page(n) for n in numbers if wanted is None or n in wanted]
        title = doc.info.title
        if ocr:
            warnings += PageOCR(language=language).read_pages(doc, chosen)
    describer = ImageDescriber(language=language)
    if describe:
        warnings += describer.describe_pages(chosen)
    describer.apply_cached(chosen)
    return from_pages(chosen), title, warnings
