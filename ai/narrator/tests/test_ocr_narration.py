"""The narrator with OCR pages (document-reader phase 4): exact text, Arabic and English."""
import io

import pytest

from conftest import NOW, config
from narrator import FileNarrator


def scan_png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(im).text((100, 150), "SCANNED", fill="black", font=ImageFont.load_default(size=72))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def mixed_pdf(tmp_path):
    """Page 1 has a text layer; page 2 is only a scanned image."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "This first page has a real text layer to read.", fontsize=12)
    page = doc.new_page()
    page.insert_image(page.rect, stream=scan_png())
    path = tmp_path / "mixed.pdf"
    doc.save(str(path))
    return path


ANSWER = {"blocks": [{"kind": "heading", "level": 1, "text": "الفصل الثاني"},
                     {"kind": "paragraph", "text": "تعتمد الدراسة على عينة من 36 طالباً."},
                     {"kind": "handwritten", "text": "مهم للامتحان"}]}


class FakeOCR:
    model = "fake-vision"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer or ANSWER, error, 0

    def describe(self, image, mime, prompt, schema):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.answer)


class FakeTesseract:
    path = "tesseract"

    def missing_languages(self):
        return []

    def read(self, image):
        return {"blocks": [{"kind": "paragraph", "text": "نص من القارئ المحلي"}]}


def reader_ocr(engine, language, tesseract=None):
    from reader import PageOCR, ReaderConfig
    return PageOCR(ReaderConfig.from_env(), engine=engine, language=language, tesseract=tesseract)


@pytest.mark.parametrize("lang, expected", [
    ("mixed", ["صفحة 2 من 2: الفصل الثاني.", "نص مستخرج تلقائياً من صورة الصفحة.",
               "تعتمد الدراسة على عينة من 36 طالباً.", "ملاحظة بخط اليد: مهم للامتحان."]),
    ("en", ["Page 2 of 2: الفصل الثاني.", "Text extracted automatically from the page image.",
            "تعتمد الدراسة على عينة من 36 طالباً.", "Handwritten note: مهم للامتحان."])])
def test_ocr_page_is_announced_and_handwriting_is_read(mixed_pdf, lang, expected):
    engine = FakeOCR()
    narration = FileNarrator(config(lang)).narrate(mixed_pdf, {}, now=NOW, ocr_reader=reader_ocr(engine, lang))
    assert engine.calls == 1                                         # only the scanned page is sent
    assert [s.text for s in narration.units[1]] == expected
    assert [s.kind for s in narration.units[1]] == ["position", "ocr_notice", "content", "handwritten"]
    assert narration.units[1][1].position["engine"] == "gemini"
    assert all(s.kind != "ocr_notice" for s in narration.units[0])  # the text page has no notice
    assert ("ولا يحتوي على صور أو جداول" if lang != "en" else "It has no images or tables") in narration.intro.text


def test_tesseract_page_says_local_reader_and_possible_mistakes(mixed_pdf):
    from reader import VisionUnavailableError
    engine = FakeOCR(error=VisionUnavailableError("GEMINI_API_KEY is not set"))
    narration = FileNarrator(config("ar")).narrate(
        mixed_pdf, {}, now=NOW, ocr_reader=reader_ocr(engine, "ar", FakeTesseract()))
    assert [s.text for s in narration.units[1]] == [
        "صفحة 2 من 2.", "نص مستخرج تلقائياً من صورة الصفحة بقارئ محلي، وقد تكون فيه أخطاء.",
        "نص من القارئ المحلي"]
    assert narration.units[1][1].position["engine"] == "tesseract"
    assert any("used Tesseract" in w for w in narration.warnings)
    en = FileNarrator(config("en")).narrate(
        mixed_pdf, {}, now=NOW, ocr_reader=reader_ocr(FakeOCR(error=VisionUnavailableError("x")), "en",
                                                     FakeTesseract()))
    assert en.units[1][1].text == ("Text extracted automatically from the page image with a local reader; "
                                   "it may contain mistakes.")


def test_scanned_page_without_ocr_and_ocr_only_for_requested_units(mixed_pdf):
    plain = FileNarrator(config("ar")).narrate(mixed_pdf, {}, now=NOW)
    assert [s.text for s in plain.units[1]] == ["صفحة 2 من 2.", "صفحة ممسوحة لم يُستخرج نصها بعد، وتحتاج OCR."]
    engine = FakeOCR()
    FileNarrator(config("ar")).narrate(mixed_pdf, {}, now=NOW, ocr_reader=reader_ocr(engine, "ar"), units={1})
    assert engine.calls == 0
