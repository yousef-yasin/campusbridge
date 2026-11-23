"""Phase 4: OCR of scanned pages and photos, with a fake vision engine and generated scans."""
import io
import json
from pathlib import Path

import pytest

from reader import PageOCR, UNCLEAR, VisionUnavailableError, open_document, to_speech_text
from reader.__main__ import main
from reader.ocr import PROMPT, PROMPT_VERSION, SCHEMA, Tesseract, parse_tsv

INTRO = "نص مستخرج تلقائياً من صورة الصفحة."
ANSWER = {"language": "ar", "blocks": [
    {"kind": "heading", "level": 1, "text": "شجرة الزيتون"},
    {"kind": "paragraph", "text": f"تُعد شجرة الزيتون من أقدم الأشجار {UNCLEAR} في حوض المتوسط."},
    {"kind": "list", "items": ["1. الزيت", "2. الخشب"]},
    {"kind": "table", "rows": [["الموسم", "الإنتاج"], ["2023/24", "2.589"], ["2024/25", "3.572"]]},
]}


def page_picture(text="SCANNED PAGE", size=(1240, 1754), color="white") -> bytes:
    """A white 'paper' with big black text, as PNG."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=72)
    draw.text((100, 150), text, fill="black", font=font)
    draw.text((100, 300), "Line two of the page", fill="black", font=font)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def scanned_pdf(path: Path, text_first_page: bool = False) -> Path:
    """Page(s) made only of an image (no text layer); optionally a normal text page first."""
    import pymupdf
    doc = pymupdf.open()
    if text_first_page:
        page = doc.new_page()
        page.insert_text((72, 100), "Introduction", fontsize=20)
        page.insert_text((72, 140), "This first page has a real text layer.", fontsize=12)
    page = doc.new_page()
    page.insert_image(page.rect, stream=page_picture())
    doc.save(str(path))
    return path


class FakeOCR:
    model = "fake-vision"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer or ANSWER, error, []

    def describe(self, image, mime, prompt, schema):
        from PIL import Image
        with Image.open(io.BytesIO(image)) as im:
            self.calls.append({"size": im.size, "mime": mime, "prompt": prompt, "schema": schema})
        if self.error:
            raise self.error
        return json.loads(json.dumps(self.answer))


class FakeTesseract:
    path = "tesseract"

    def __init__(self, missing=()):
        self.missing, self.calls = list(missing), 0

    def missing_languages(self):
        return self.missing

    def read(self, image):
        self.calls += 1
        return {"blocks": [{"kind": "paragraph", "text": f"نص من القارئ المحلي {UNCLEAR}"}]}


def texts(page):
    return [(b.kind, b.text, b.source) for b in page.blocks]


# --- reading a scanned page ----------------------------------------------------------------

def test_scanned_pdf_page_becomes_unified_blocks(tmp_path, cfg):
    engine = FakeOCR()
    with open_document(scanned_pdf(tmp_path / "scan.pdf"), cfg) as doc:
        page = doc.page(1)
        assert page.needs_ocr and [b.kind for b in page.blocks] == ["image"]
        warnings = PageOCR(cfg, engine=engine, tesseract=None).read_pages(doc, [page])
    assert warnings == [] and len(engine.calls) == 1
    call = engine.calls[0]
    assert call["mime"] == "image/png" and call["size"] == (1653, 2339)        # A4 page at 200 dpi
    assert call["prompt"] == PROMPT and call["schema"] == SCHEMA
    for rule in ("exactly as written", "Never", "translate", UNCLEAR, "right to left", "header row first",
                 "Arabic comma (،)", "not a table", "handwritten: a note written by hand"):
        assert rule in PROMPT
    assert texts(page) == [
        ("heading", "شجرة الزيتون", "ocr"),
        ("paragraph", f"تُعد شجرة الزيتون من أقدم الأشجار {UNCLEAR} في حوض المتوسط.", "ocr"),
        ("list", "1. الزيت\n2. الخشب", "ocr"),
        ("table", "الموسم: 2023/24، الإنتاج: 2.589\nالموسم: 2024/25، الإنتاج: 3.572", "ocr")]
    assert page.blocks[3].table["columns"] == ["الموسم", "الإنتاج"]           # the scan image is gone
    assert page.ocr == {"status": "done", "engine": "gemini", "model": "fake-vision", "language": "mixed",
                        "cached": False, "blocks": 4, "unclear_words": 1, "handwritten": False}
    assert page.warnings == [f"OCR: 1 unclear word(s) marked {UNCLEAR}"]
    speech = to_speech_text(page)[0].text.split("\n\n")
    assert speech == [INTRO, "شجرة الزيتون.",
                      "تُعد شجرة الزيتون من أقدم الأشجار (كلمة غير واضحة) في حوض المتوسط.",
                      "1. الزيت.\n2. الخشب.",
                      "جدول، عدد صفوفه 2.\nالموسم: 2023/24، الإنتاج: 2.589.\nالموسم: 2024/25، الإنتاج: 3.572."]


def test_english_mode_phrases(tmp_path, cfg):
    with open_document(scanned_pdf(tmp_path / "scan.pdf"), cfg) as doc:
        page = doc.page(1)
        PageOCR(cfg, engine=FakeOCR(), tesseract=None, language="en").read_pages(doc, [page])
    speech = to_speech_text(page)[0].text
    assert speech.startswith("Text extracted automatically from the page image.\n\n")
    assert "الأشجار (unclear word) في" in speech


def test_mixed_pdf_reads_text_pages_and_ocrs_scanned_pages(tmp_path, cfg):
    engine = FakeOCR()
    with open_document(scanned_pdf(tmp_path / "mixed.pdf", text_first_page=True), cfg) as doc:
        info = doc.info
        pages = list(doc.pages())
        PageOCR(cfg, engine=engine, tesseract=None).read_pages(doc, pages)
    assert info.ocr_pages == [2] and len(engine.calls) == 1
    assert [b.source for b in pages[0].blocks] == [None, None] and pages[0].ocr is None
    assert pages[1].blocks[0].text == "شجرة الزيتون"
    speech = to_speech_text(pages)
    assert not speech[0].text.startswith(INTRO) and "Introduction" in speech[0].text
    assert speech[1].text.startswith(INTRO)


def test_cache_by_page_image_model_and_prompt_version(tmp_path, cfg):
    path = scanned_pdf(tmp_path / "scan.pdf")
    engine = FakeOCR()
    with open_document(path, cfg) as doc:
        PageOCR(cfg, engine=engine, tesseract=None).read_pages(doc, [doc.page(1)])
        page = doc.page(1)
        ocr = PageOCR(cfg, engine=engine, tesseract=None)
        ocr.read_pages(doc, [page])
        assert len(engine.calls) == 1 and ocr.calls == 0 and page.ocr["cached"] is True
        files = list(Path(cfg.ocr_dir).iterdir())
        assert len(files) == 1 and files[0].name.endswith(f"__fake-vision__v{PROMPT_VERSION}.json")
        record = json.loads(files[0].read_text(encoding="utf-8"))
        assert record["source"] == {"file": "scan.pdf", "page": 1} and record["result"] == ANSWER
        other = FakeOCR()
        other.model = "another-model"
        PageOCR(cfg, engine=other, tesseract=None).read_pages(doc, [doc.page(1)])
        assert len(other.calls) == 1                                 # the model is part of the key


def test_text_pages_are_never_sent(tmp_path, cfg):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "A normal page with enough text to read.", fontsize=12)
    doc.save(str(tmp_path / "text.pdf"))
    engine = FakeOCR()
    with open_document(tmp_path / "text.pdf", cfg) as d:
        page = d.page(1)
        PageOCR(cfg, engine=engine, tesseract=None).read_pages(d, [page])
    assert engine.calls == [] and page.ocr is None


# --- image files ---------------------------------------------------------------------------

def test_photo_file_is_one_page_turned_upright_by_exif(tmp_path, cfg):
    from PIL import Image
    im = Image.open(io.BytesIO(page_picture(size=(900, 600))))
    exif = Image.Exif()
    exif[0x0112] = 6                                    # "rotate 90° clockwise to display"
    im.save(tmp_path / "photo.jpg", "JPEG", exif=exif.tobytes())
    engine = FakeOCR()
    with open_document(tmp_path / "photo.jpg", cfg) as doc:
        assert (doc.file_type, doc.unit_count) == ("image", 1)
        page = doc.page(1)
        assert page.needs_ocr and "EXIF orientation" in page.warnings[0]
        image = page.blocks[0].image
        assert (image["width"], image["height"]) == (600, 900)       # upright: portrait
        PageOCR(cfg, engine=engine, tesseract=None).read_pages(doc, [page])
    assert engine.calls[0]["size"] == (600, 900) and engine.calls[0]["mime"] == "image/jpeg"
    assert page.blocks[0].source == "ocr" and all(b.kind != "image" for b in page.blocks)
    for ext in ("png", "webp"):
        Image.new("RGB", (300, 200), "white").save(tmp_path / f"p.{ext}")
        with open_document(tmp_path / f"p.{ext}", cfg) as doc:
            assert doc.file_type == "image" and not doc.page(1).warnings


def test_photo_without_text_keeps_the_picture(tmp_path, cfg):
    from PIL import Image
    Image.new("RGB", (400, 300), (20, 120, 40)).save(tmp_path / "tree.png")
    with open_document(tmp_path / "tree.png", cfg) as doc:
        page = doc.page(1)
        PageOCR(cfg, engine=FakeOCR({"blocks": []}), tesseract=None).read_pages(doc, [page])
    assert page.ocr["status"] == "no_text" and [b.kind for b in page.blocks] == ["image"]
    assert to_speech_text(page)[0].text == ""                     # nothing announced: just a picture


# --- when Gemini cannot be used -------------------------------------------------------------

def test_tesseract_fallback_when_gemini_is_unavailable(tmp_path, cfg):
    import pymupdf
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page().insert_image(pymupdf.Rect(0, 0, 612, 792), stream=page_picture())
    doc.save(str(tmp_path / "two.pdf"))
    engine = FakeOCR(error=VisionUnavailableError("GEMINI_API_KEY is not set"))
    tess = FakeTesseract()
    with open_document(tmp_path / "two.pdf", cfg) as d:
        pages = list(d.pages())
        warnings = PageOCR(cfg, engine=engine, tesseract=tess).read_pages(d, pages)
    assert len(engine.calls) == 1 and tess.calls == 2               # no more Gemini calls after the first
    assert all(p.ocr["engine"] == "tesseract" and p.ocr["model"] is None for p in pages)
    assert len(warnings) == 1 and "used Tesseract" in warnings[0] and "quality is lower" in warnings[0]
    assert to_speech_text(pages[0])[0].text == (
        "نص مستخرج تلقائياً من صورة الصفحة بقارئ محلي، وقد تكون فيه أخطاء.\n\n"
        "نص من القارئ المحلي (كلمة غير واضحة)")
    assert list(Path(cfg.ocr_dir).glob("*.json")) == []              # Tesseract results are not cached


def test_no_tesseract_explains_how_to_install_and_marks_the_page(tmp_path, cfg):
    engine = FakeOCR(error=VisionUnavailableError("Gemini unreachable (internet required)"))
    with open_document(scanned_pdf(tmp_path / "scan.pdf"), cfg) as doc:
        page = doc.page(1)
        warnings = PageOCR(cfg, engine=engine, tesseract=None).read_pages(doc, [page])
    assert page.ocr["status"] == "needs_ocr" and "unreachable" in page.ocr["reason"]
    assert "Tesseract is not installed" in warnings[0] and "tesseract-ocr-ara" in warnings[0]
    assert to_speech_text(page)[0].text == "صفحة ممسوحة لم يُستخرج نصها بعد، وتحتاج OCR."
    tess = FakeTesseract(missing=["ara"])
    with open_document(scanned_pdf(tmp_path / "scan2.pdf"), cfg) as doc:
        page = doc.page(1)
        warnings = PageOCR(cfg, engine=engine, tesseract=tess).read_pages(doc, [page])
    assert page.ocr["status"] == "needs_ocr" and "ara.traineddata" in warnings[0] and tess.calls == 0


def test_page_limit_per_run(tmp_path, cfg):
    cfg.ocr_max_pages = 0
    engine = FakeOCR()
    with open_document(scanned_pdf(tmp_path / "scan.pdf"), cfg) as doc:
        page = doc.page(1)
        PageOCR(cfg, engine=engine, tesseract=None).read_pages(doc, [page])
    assert engine.calls == [] and "READER_OCR_MAX_PAGES" in page.ocr["reason"]


def test_scanned_page_without_ocr_says_so(tmp_path, cfg):
    with open_document(scanned_pdf(tmp_path / "scan.pdf"), cfg) as doc:
        page = doc.page(1)
    assert to_speech_text(page)[0].text == "صفحة ممسوحة لم يُستخرج نصها بعد، وتحتاج OCR."


def test_tesseract_tsv_marks_low_confidence_words():
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    rows = [(5, 1, 1, 1, 1, 96, "شجرة"), (5, 1, 1, 1, 2, 12, "الزيتون"), (5, 1, 1, 2, 1, 90, "قديمة"),
            (5, 2, 1, 1, 1, 88, "Olive"), (5, 2, 1, 1, 2, 91, "tree"), (4, 2, 1, 1, 0, -1, "")]
    tsv = head + "".join(f"{lv}\t1\t{b}\t{p}\t{l}\t{w}\t0\t0\t1\t1\t{c}\t{t}\n" for lv, b, p, l, w, c, t in rows)
    assert parse_tsv(tsv) == [{"kind": "paragraph", "text": f"شجرة {UNCLEAR} قديمة"},
                              {"kind": "paragraph", "text": "Olive tree"}]


@pytest.mark.skipif(not Tesseract.find(__import__("reader").ReaderConfig()), reason="Tesseract is not installed")
def test_real_tesseract_reads_a_generated_page(cfg):
    tess = Tesseract(cfg)
    assert tess.missing_languages() == []
    text = " ".join(b["text"] for b in tess.read(page_picture("HELLO OCR TEST"))["blocks"])
    assert "HELLO" in text and "OCR" in text


def test_cli_ocr_option(tmp_path, cfg, capsys, monkeypatch):
    monkeypatch.setattr("reader.ocr.Tesseract.find", staticmethod(lambda config: None))
    path = scanned_pdf(tmp_path / "scan.pdf")
    assert main(["extract", str(path), "--ocr"]) == 0                 # no key, no Tesseract: keeps going
    captured = capsys.readouterr()
    assert "[needs OCR: no text layer] (GEMINI_API_KEY is not set" in captured.out
    assert "Tesseract is not installed" in captured.err


def test_punctuation_moved_by_right_to_left_order_is_put_back():
    from reader.ocr import to_blocks
    result = {"blocks": [{"kind": "paragraph", "text": "منذ آلاف السنين .وهي شجرة دائمة، الخضرة ،وتنتشر"},
                         {"kind": "paragraph", "text": "z = 0.5 and x .y stay as written"}]}
    assert [b.text for b in to_blocks(result, 1)] == ["منذ آلاف السنين. وهي شجرة دائمة، الخضرة، وتنتشر",
                                                       "z = 0.5 and x .y stay as written"]


def test_answer_without_the_schema_using_type_instead_of_kind():
    # Real answer (photo of a printed page, last retry without the schema): "type", not "kind".
    from reader.ocr import to_blocks
    result = {"blocks": [{"type": "heading", "level": 1, "text": "Why big data?"},
                         {"type": "list", "items": ["Increase of storage capacities."]},
                         {"items": ["Cost Saving", "Time Saving"]},
                         {"rows": [["A", "B"], ["1", "2"]]},
                         {"text": "plain"}]}
    assert [(b.kind, b.text) for b in to_blocks(result, 1)] == [
        ("heading", "Why big data?"), ("list", "Increase of storage capacities."),
        ("list", "Cost Saving\nTime Saving"), ("table", "A: 1; B: 2"), ("paragraph", "plain")]


def test_handwriting_is_its_own_block_and_is_announced(tmp_path, cfg):
    # Real case: a printed English page with Arabic words written by hand above some words.
    answer = {"blocks": [
        {"kind": "list", "items": ["The need to analyze real-time data."]},
        {"kind": "handwritten", "text": "تحليل"},
        {"kind": "handwritten", "text": f"تنافسية {UNCLEAR}"}]}
    for mode, expected in (("mixed", ["ملاحظة بخط اليد: تحليل.",
                                      "ملاحظة بخط اليد: تنافسية (كلمة غير واضحة)."]),
                           ("en", ["Handwritten note: تحليل.", "Handwritten note: تنافسية (unclear word)."])):
        with open_document(scanned_pdf(tmp_path / f"notes-{mode}.pdf"), cfg) as doc:
            page = doc.page(1)
            PageOCR(cfg, engine=FakeOCR(answer), tesseract=None, language=mode).read_pages(doc, [page])
        assert [(b.kind, b.source) for b in page.blocks] == [("list", "ocr"), ("handwritten", "ocr"),
                                                             ("handwritten", "ocr")]
        assert to_speech_text(page)[0].text.split("\n\n")[2:] == expected
    assert "handwritten" in SCHEMA["properties"]["blocks"]["items"]["properties"]["kind"]["enum"]
    assert "Never mix handwriting into" in PROMPT


def test_a_handwritten_page_is_announced_once_and_read_as_normal_text(tmp_path, cfg):
    # Real case: a sheet written by hand in Arabic with a few English words.
    answer = {"handwritten_page": True, "blocks": [
        {"kind": "heading", "text": "Slide 4 - project idea."},
        {"kind": "handwritten", "text": "وهنا هون اجت فكرتنا"},
        {"kind": "paragraph", "text": "منصة تفاعلية تحول بيانات ناسا من 2000 الى 2026"}]}
    for mode, lead in (("mixed", "نص مستخرج تلقائياً من صورة الصفحة. الورقة مكتوبة بخط اليد."),
                       ("en", "Text extracted automatically from the page image. The page is handwritten.")):
        with open_document(scanned_pdf(tmp_path / f"hand-{mode}.pdf"), cfg) as doc:
            page = doc.page(1)
            PageOCR(cfg, engine=FakeOCR(answer), tesseract=None, language=mode).read_pages(doc, [page])
        assert [b.kind for b in page.blocks] == ["heading", "paragraph", "paragraph"] and page.ocr["handwritten"]
        speech = to_speech_text(page)[0].text.split("\n\n")
        assert speech[0] == lead and speech[2] == "وهنا هون اجت فكرتنا"     # no «ملاحظة بخط اليد» per line
        assert sum("خط اليد" in part or "handwritten" in part.lower() for part in speech) == 1
    assert "handwritten_page: true when all or most of the page is written by hand" in PROMPT
    # Without the flag: mostly handwritten blocks also make a handwritten page
    from reader.ocr import is_handwritten_page
    assert is_handwritten_page({"blocks": [{"kind": "handwritten", "text": "نص طويل مكتوب باليد هنا"},
                                           {"kind": "heading", "text": "Title"}]})
    assert not is_handwritten_page({"blocks": [{"kind": "paragraph", "text": "نص مطبوع طويل جداً في الصفحة"},
                                               {"kind": "handwritten", "text": "تحليل"}]})


def test_handwritten_page_without_internet_is_not_read_by_tesseract(tmp_path, cfg):
    class HandTesseract(FakeTesseract):
        def read(self, image):                     # Tesseract on a handwritten sheet: low confidence
            self.calls += 1
            return {"blocks": [{"kind": "paragraph", "text": "وهنا هرن احت فكرتلا"}],
                    "confidence": {"words": 105, "median": 52.0, "low_share": 0.25}}
    engine = FakeOCR(error=VisionUnavailableError("Gemini unreachable (internet required)"))
    with open_document(scanned_pdf(tmp_path / "hand.pdf"), cfg) as doc:
        page = doc.page(1)
        warnings = PageOCR(cfg, engine=engine, tesseract=HandTesseract()).read_pages(doc, [page])
    assert page.ocr["status"] == "handwritten_offline" and "cannot read handwriting" in warnings[0]
    assert all(b.source != "ocr" for b in page.blocks)                    # the wrong text is not used
    assert to_speech_text(page)[0].text == (
        "الورقة مكتوبة بخط اليد على الأغلب، ولا يمكن قراءتها بدون إنترنت. جرّب مرة أخرى عند توفر الاتصال.")
    from reader.ocr import confidence_stats, looks_handwritten
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    printed = head + "".join(f"5\t1\t1\t1\t1\t{i}\t0\t0\t1\t1\t{c}\tw{i}\n" for i, c in enumerate([96, 91, 88, 20, 95]))
    assert confidence_stats(printed) == {"words": 5, "median": 91.0, "low_share": 0.2}
    assert not looks_handwritten({"median": 88, "low_share": 0.12}) and looks_handwritten({"median": 52, "low_share": 0.25})


@pytest.mark.parametrize("ipv4", [False, True])
def test_ocr_client_uses_the_shared_ipv4_option(cfg, monkeypatch, ipv4):
    """OCR (and image descriptions) build their Gemini client with ai/shared's http_options:
    CB_GEMINI_IPV4=1 binds the connection to IPv4, otherwise the defaults are kept."""
    from google import genai
    made = {}
    monkeypatch.setattr(genai, "Client", lambda **kw: made.update(kw) or "client")
    if ipv4:
        monkeypatch.setenv("CB_GEMINI_IPV4", "1")
    ocr = PageOCR(cfg, tesseract=None)
    assert ocr.engine._get_client("test-key") == "client"
    options = made["http_options"]
    assert made["api_key"] == "test-key" and options.timeout == cfg.vision_timeout * 1000
    if ipv4:
        pool = options.client_args["transport"]._pool
        assert pool._local_address == "0.0.0.0"
    else:
        assert options.client_args is None
