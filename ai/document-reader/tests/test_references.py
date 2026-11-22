"""References and footnotes become a "references" block, announced but not read by default."""
import pytest

from reader import PageOCR, open_document, to_speech_text
from reader.__main__ import main
from reader.references import mark_references
from reader.model import Block, Page

NOTE = "في مراجع بآخر الصفحة."


def page(*blocks):
    return Page(1, "page", blocks=[Block(kind, text, "ar", 1, level=level) for kind, text, level in blocks])


def kinds(p):
    return [b.kind for b in p.blocks]


def test_footnotes_at_the_bottom_of_the_page():
    # Real shape (OCR of a book page): body refers to (1) and (2), footnotes at the bottom.
    p = mark_references(page(
        ("paragraph", "وبروميد الماغنيسيوم المستعمل في صناعة الأدوية(1).", None),
        ("paragraph", "من مجمل الطاقة الكهربائية المولدة في الأردن (2).", None),
        ("paragraph", "(1) الموسوعة الأردنية، ج 1، ص 66. (2) خريسات وآخرون، محاضرات في تاريخ الأردن، ص 24.", None)))
    assert kinds(p) == ["paragraph", "paragraph", "references"]
    assert p.blocks[2].items == ["(1) الموسوعة الأردنية، ج 1، ص 66.",
                                 "(2) خريسات وآخرون، محاضرات في تاريخ الأردن، ص 24."]
    speech = to_speech_text(p)[0].text.split("\n\n")
    assert speech[-1] == NOTE and "الموسوعة" not in to_speech_text(p)[0].text
    assert to_speech_text(p, include_references=True)[0].text.split("\n\n")[-1] == (
        "المراجع:\n(1) الموسوعة الأردنية، ج 1، ص 66.\n(2) خريسات وآخرون، محاضرات في تاريخ الأردن، ص 24.")


@pytest.mark.parametrize("body, foot", [("Water boils at 100 degrees [1].", "[1] Smith, Physics, p. 12."),
                                        ("Water boils at 100 degrees¹.", "¹ Smith, Physics, p. 12."),
                                        ("Water boils at 100 degrees1.", "(1) Smith, Physics, p. 12.")])
def test_footnote_markers(body, foot):
    assert kinds(mark_references(page(("paragraph", body, None), ("paragraph", foot, None)))) == \
        ["paragraph", "references"]


def test_a_numbered_list_at_the_end_is_not_a_footnote():
    p = mark_references(page(("paragraph", "Steps to follow:", None), ("paragraph", "(1) Mix the water.", None),
                             ("paragraph", "(2) Heat it to 100 degrees.", None)))
    assert kinds(p) == ["paragraph", "paragraph", "paragraph"]


def test_titled_section_until_the_next_heading():
    p = mark_references(page(("heading", "Introduction", 1), ("paragraph", "As shown in [1].", None),
                             ("heading", "References", 1), ("paragraph", "[1] A. Author, Book, 2020.", None),
                             ("list", "[2] B. Author, Paper, 2021.", None), ("heading", "Appendix", 1),
                             ("paragraph", "Extra tables.", None)))
    assert kinds(p) == ["heading", "paragraph", "references", "heading", "paragraph"]
    assert p.blocks[2].text.split("\n") == ["References", "[1] A. Author, Book, 2020.", "[2] B. Author, Paper, 2021."]
    for title in ("المراجع", "المصادر:", "قائمة المراجع", "Bibliography"):
        q = mark_references(page(("heading", title, 2), ("paragraph", "مرجع أول، 2020.", None)))
        assert kinds(q) == ["references"]
    assert to_speech_text(page(("heading", "References", 1)))[0].text == "References."   # empty section


def test_english_mode_note(monkeypatch):
    monkeypatch.setenv("CB_EXPLAIN_LANGUAGE", "en")
    p = mark_references(page(("paragraph", "Seen in [1].", None), ("paragraph", "[1] Smith, 2020.", None)))
    assert to_speech_text(p)[0].text.endswith("There are references at the end of the page.")
    assert to_speech_text(p, include_references=True)[0].text.endswith("References:\n[1] Smith, 2020.")


def test_docx_file_and_cli(tmp_path, cfg, capsys):
    from docx import Document
    d = Document()
    d.add_heading("مقدمة", 1)
    d.add_paragraph("تنتشر شجرة الزيتون في حوض المتوسط [1].")
    d.add_heading("المراجع", 1)
    d.add_paragraph("[1] المجلس الدولي للزيتون، 2025.")
    d.save(str(tmp_path / "r.docx"))
    with open_document(tmp_path / "r.docx", cfg) as doc:
        p = doc.page(1)
        outline = [e.title for e in doc.info.outline]
    assert kinds(p) == ["heading", "paragraph", "references"] and outline == ["مقدمة"]
    assert main(["extract", str(tmp_path / "r.docx"), "--speech"]) == 0
    assert capsys.readouterr().out.strip().endswith(NOTE)
    assert main(["extract", str(tmp_path / "r.docx"), "--speech", "--references"]) == 0
    assert "المراجع:\n[1] المجلس الدولي للزيتون، 2025." in capsys.readouterr().out


def test_footnotes_found_after_ocr(tmp_path, cfg):
    import io
    import pymupdf
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1240, 1754), "white").save(buf, "PNG")
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=buf.getvalue())
    doc.save(str(tmp_path / "scan.pdf"))

    class Fake:
        model = "fake-vision"

        def describe(self, image, mime, prompt, schema):
            return {"blocks": [{"kind": "paragraph", "text": "تستخدم في صناعة الأدوية(1)."},
                               {"kind": "paragraph", "text": "(1) الموسوعة الأردنية، ص 66."}]}
    with open_document(tmp_path / "scan.pdf", cfg) as d:
        p = d.page(1)
        PageOCR(cfg, engine=Fake(), tesseract=None).read_pages(d, [p])
    assert kinds(p) == ["paragraph", "references"] and p.blocks[1].source == "ocr"
    assert to_speech_text(p)[0].text.endswith(NOTE)
