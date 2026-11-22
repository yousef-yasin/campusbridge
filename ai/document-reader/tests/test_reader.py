import json
from pathlib import Path

import pytest

from conftest import AR_HEADING, AR_LEFT, AR_RIGHT, png
from reader import (CorruptFileError, InputNotFoundError, PageNotFoundError, PasswordProtectedError,
                    ReaderConfig, UnsupportedFormatError, open_document, to_speech_text)
from reader.__main__ import main


def kinds(page):
    return [(b.kind, b.text) for b in page.blocks]


# --- formats and errors ------------------------------------------------------------------

@pytest.mark.parametrize("ext, stream, app", [("doc", "WordDocument", "Word"),
                                              ("ppt", "PowerPoint Document", "PowerPoint"),
                                              ("xls", "Workbook", "Excel")])
def test_old_office_formats_ask_to_save_as_new_format(tmp_path, ext, stream, app):
    path = tmp_path / f"old.{ext}"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504 + stream.encode("utf-16-le"))
    with pytest.raises(UnsupportedFormatError) as err:
        open_document(path)
    assert f".{ext})" in str(err.value) and "Save As" in str(err.value) and app in str(err.value)
    renamed = tmp_path / f"renamed.{ext}x"                  # old content with a new extension
    renamed.write_bytes(path.read_bytes())
    with pytest.raises(UnsupportedFormatError, match=f"\\.{ext}\\)"):
        open_document(renamed)


def test_other_file_problems(tmp_path):
    with pytest.raises(InputNotFoundError):
        open_document(tmp_path / "missing.pdf")
    (tmp_path / "empty.docx").write_bytes(b"")
    with pytest.raises(InputNotFoundError):
        open_document(tmp_path / "empty.docx")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="supported: .docx, .pdf, .pptx, .xlsx"):
        open_document(tmp_path / "notes.txt")
    (tmp_path / "broken.docx").write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(CorruptFileError):
        open_document(tmp_path / "broken.docx")
    encrypted = tmp_path / "secret.docx"
    encrypted.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "EncryptedPackage".encode("utf-16-le"))
    with pytest.raises(PasswordProtectedError):
        open_document(encrypted)


def test_password_protected_pdf(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(str(tmp_path / "locked.pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw="pw", owner_pw="owner")
    with pytest.raises(PasswordProtectedError):
        open_document(tmp_path / "locked.pdf")


def test_content_wins_over_extension(docx_file, cfg):
    renamed = docx_file.with_suffix(".pdf")
    renamed.write_bytes(docx_file.read_bytes())
    with open_document(renamed, cfg) as doc:
        assert doc.file_type == "docx"
        assert "file extension is .pdf but the content is docx" in doc.info.warnings


# --- Word ------------------------------------------------------------------------------

def test_docx_blocks_pages_and_languages(docx_file, cfg):
    with open_document(docx_file, cfg) as doc:
        assert doc.unit_count == 2
        p1 = doc.page(1)
        assert kinds(p1)[:4] == [
            ("heading", "مقدمة في الذكاء الاصطناعي"),
            ("paragraph", "اليوم سنتحدث عن machine learning وكيف يتعلم الحاسوب من البيانات."),
            ("list", "النقطة الأولى\nالنقطة الثانية"),
            ("table", "الاسم: أحمد، الدرجة: 90\nالاسم: سارة، الدرجة: 85")]
        assert [b.lang for b in p1.blocks[:4]] == ["ar", "mixed", "ar", "ar"]
        assert p1.blocks[2].items == ["النقطة الأولى", "النقطة الثانية"]
        assert p1.blocks[3].table == {"columns": ["الاسم", "الدرجة"], "rows": [["أحمد", "90"], ["سارة", "85"]]}
        images = [b for b in p1.blocks if b.kind == "image"]
        assert len(images) == 1 and (images[0].image["width"], images[0].image["height"]) == (200, 150)
        assert kinds(doc.page(2)) == [("heading", "Machine Learning Basics"),
                                      ("heading", "Supervised learning"),
                                      ("paragraph", "Models learn from labelled examples.")]
        assert [b.level for b in doc.page(2).blocks[:2]] == [1, 2]


def test_docx_info_and_outline(docx_file, cfg):
    with open_document(docx_file, cfg) as doc:
        info = doc.info
    assert (info.title, info.file_type, info.unit_type, info.unit_count) == (
        "مقدمة في الذكاء الاصطناعي", "docx", "page", 2)
    assert (info.image_count, info.table_count, info.language, info.needs_ocr) == (1, 1, "mixed", False)
    assert [(e.title, e.unit, e.level) for e in info.outline] == [
        ("مقدمة في الذكاء الاصطناعي", 1, 1), ("Machine Learning Basics", 2, 1), ("Supervised learning", 2, 2)]


def test_docx_without_saved_page_breaks_warns(tmp_path, cfg):
    import docx
    d = docx.Document()
    d.add_paragraph("فقرة أولى")
    d.add_paragraph("فقرة ثانية")
    d.save(str(tmp_path / "flat.docx"))
    with open_document(tmp_path / "flat.docx", cfg) as doc:
        assert doc.unit_count == 1
        assert any("no saved page breaks" in w for w in doc.info.warnings)


def test_docx_bold_lines_are_headings_when_no_heading_styles(tmp_path, cfg):
    import docx
    d = docx.Document()
    d.add_paragraph().add_run("الفصل الأول").bold = True
    d.add_paragraph("نص عادي في الفقرة.")
    d.add_paragraph().add_run("ملاحظة: هذا نص عريض لكنه جملة.").bold = True
    d.save(str(tmp_path / "bold.docx"))
    with open_document(tmp_path / "bold.docx", cfg) as doc:
        assert [b.kind for b in doc.page(1).blocks] == ["heading", "paragraph", "paragraph"]
        assert [e.title for e in doc.info.outline] == ["الفصل الأول"]


# --- PowerPoint --------------------------------------------------------------------------

def test_pptx_slides_notes_tables_and_rtl_order(pptx_file, cfg):
    with open_document(pptx_file, cfg) as doc:
        assert doc.unit_count == 4
        assert kinds(doc.page(1)) == [("heading", "مقدمة في تعلم الآلة"), ("heading", "المحاضرة الأولى")]
        s2 = doc.page(2)
        assert [b.kind for b in s2.blocks] == ["heading", "list", "image", "notes"]
        assert s2.blocks[1].items == ["التعلم الموجه supervised", "التعلم غير الموجه"]
        assert s2.blocks[1].lang == "mixed"
        assert s2.blocks[3].text == "اشرح الفرق بمثال من الحياة اليومية."
        s3 = doc.page(3)
        assert kinds(s3)[:3] == [("heading", "مقارنة"), ("paragraph", "العمود الأيمن"),
                                 ("paragraph", "العمود الأيسر")]          # right column first (RTL)
        assert s3.blocks[3].text == "النوع: موجه، مثال: تصنيف الصور\nالنوع: غير موجه، مثال: التجميع"
        assert [b.kind for b in doc.page(4).blocks] == ["heading", "list"]   # icon and logo ignored


def test_pptx_info_outline_and_images(pptx_file, cfg, tmp_path):
    with open_document(pptx_file, cfg) as doc:
        info = doc.info
        assert not (tmp_path / "images").exists()            # info does not write images
        assert (info.unit_type, info.unit_count, info.image_count, info.table_count) == ("slide", 4, 1, 1)
        assert [(e.title, e.unit) for e in info.outline] == [
            ("مقدمة في تعلم الآلة", 1), ("أنواع التعلم", 2), ("مقارنة", 3), ("Summary", 4)]
        image = doc.page(2).blocks[2].image
    saved = Path(image["path"])
    assert saved.parent == tmp_path / "images" and saved.name == f"{image['sha256'][:16]}.png"
    assert saved.read_bytes() == png(300, 200) and image["description"] == ""
    assert [p.name for p in (tmp_path / "images").iterdir()] == [saved.name]   # logo, icon skipped


def test_pptx_direct_slide_access_reads_only_that_slide(pptx_file, cfg, monkeypatch):
    with open_document(pptx_file, cfg) as doc:
        seen = []
        original = doc._shape_blocks
        monkeypatch.setattr(doc, "_shape_blocks", lambda s, n, rtl: seen.append(n) or original(s, n, rtl))
        doc.page(3)
        assert set(seen) == {3}
        with pytest.raises(PageNotFoundError, match="slide 9 does not exist"):
            doc.page(9)


# --- Excel -------------------------------------------------------------------------------

def test_xlsx_sheets_info_and_preview(xlsx_file, cfg):
    cfg.xlsx_preview_rows = 5
    with open_document(xlsx_file, cfg) as doc:
        info = doc.info
        assert (info.title, info.unit_type, info.unit_count, info.table_count) == ("سجل الدرجات", "sheet", 3, 2)
        grades = info.sheets[0]
        assert (grades.name, grades.columns, grades.row_count, grades.rtl) == (
            "الدرجات", ["الاسم", "الرقم الجامعي", "الدرجة"], 120, True)
        assert [(e.title, e.unit) for e in info.outline] == [("الدرجات", 1), ("Summary", 2), ("Empty", 3)]
        page = doc.page("الدرجات")
        assert [b.kind for b in page.blocks] == ["heading", "paragraph", "table"]
        assert page.blocks[1].text == "عدد الصفوف 120، وعدد الأعمدة 3: الاسم، الرقم الجامعي، الدرجة"
        table = page.blocks[2].table
        assert len(table["rows"]) == 5 and table["total_rows"] == 120
        assert page.blocks[2].text.split("\n")[0] == "الاسم: طالب 1، الرقم الجامعي: 2020001، الدرجة: 51"
        assert page.sheet == "الدرجات" and page.blocks[0].location == {"sheet": "الدرجات"}
        assert kinds(doc.page(2))[1:] == [("paragraph", "1 row, 2 columns: Course, Students"),
                                          ("table", "Course: AI; Students: 120")]


def test_xlsx_rows_on_request(xlsx_file, cfg):
    with open_document(xlsx_file, cfg) as doc:
        rows = list(doc.rows("الدرجات", start=50, count=3))
        assert rows == [{"الاسم": f"طالب {i}", "الرقم الجامعي": str(2020000 + i), "الدرجة": str(50 + i % 50)}
                        for i in (50, 51, 52)]
        assert list(doc.rows(1, start=119, count=10))[-1]["الاسم"] == "طالب 120"
        assert list(doc.rows("Empty")) == []
        with pytest.raises(PageNotFoundError, match="no sheet named"):
            doc.page("Nope")


# --- PDF ---------------------------------------------------------------------------------

def test_pdf_blocks_tables_images_and_ocr(pdf_file, cfg):
    with open_document(pdf_file, cfg) as doc:
        p1 = doc.page(1)
        assert kinds(p1)[:3] == [("heading", "Introduction to Machine Learning"),
                                 ("paragraph", "Machine learning lets computers learn from data."),
                                 ("list", "First idea\nSecond idea")]
        images = [b for b in p1.blocks if b.kind == "image"]
        assert len(images) == 1 and images[0].image["width"] == 200     # repeated logo ignored
        p2 = doc.page(2)
        assert kinds(p2) == [("heading", AR_HEADING), ("paragraph", AR_RIGHT), ("paragraph", AR_LEFT)]
        assert all(b.lang == "ar" for b in p2.blocks)
        p3 = doc.page(3)
        assert kinds(p3) == [("heading", "Results"),
                             ("table", "Model: CNN; Accuracy: 92\nModel: SVM; Accuracy: 85")]
        p4 = doc.page(4)
        assert p4.needs_ocr and [b.kind for b in p4.blocks] == ["image"]


def test_pdf_info_outline_and_ocr_report(pdf_file, cfg):
    with open_document(pdf_file, cfg) as doc:
        info = doc.info
    assert (info.title, info.unit_count, info.image_count, info.table_count) == (
        "Introduction to Machine Learning", 4, 2, 1)
    assert info.needs_ocr and info.ocr_pages == [4]
    assert info.warnings[0].startswith("1 of 4 pages have no text layer") and "pages 4" in info.warnings[0]
    assert [(e.title, e.unit) for e in info.outline] == [
        ("Introduction to Machine Learning", 1), (AR_HEADING, 2), ("Results", 3)]


def test_pdf_bookmarks_are_the_outline(pdf_file, cfg, tmp_path):
    import pymupdf
    doc = pymupdf.open(str(pdf_file))
    doc.set_toc([[1, "Part one", 1], [2, "Details", 3], [1, "Scans", 4]])
    doc.save(str(tmp_path / "toc.pdf"))
    with open_document(tmp_path / "toc.pdf", cfg) as reader:
        assert [(e.title, e.unit, e.level) for e in reader.info.outline] == [
            ("Part one", 1, 1), ("Details", 3, 2), ("Scans", 4, 1)]


def test_pdf_direct_page_access_processes_one_page(pdf_file, cfg):
    with open_document(pdf_file, cfg) as doc:
        processed, read_page = [], doc._read_page
        doc._read_page = lambda n: processed.append(n) or read_page(n)
        doc.page(3)
        assert processed == [3]           # tables, images, blocks: only page 3
        # The document's body font size is sampled once from the text of a few pages (cached);
        # after that, reading a page loads that page only.
        loaded, load_page = [], doc._doc.load_page
        doc._doc.load_page = lambda i: loaded.append(i) or load_page(i)
        doc.page(2)
        assert loaded == [1]


# --- speech text -------------------------------------------------------------------------

def test_to_speech_text_page_by_page(pptx_file, xlsx_file, cfg):
    with open_document(pptx_file, cfg) as doc:
        units = to_speech_text(doc.pages())
        assert [u.unit for u in units] == [1, 2, 3, 4]
        assert units[0].text == "مقدمة في تعلم الآلة.\n\nالمحاضرة الأولى."
        assert units[1].text == ("أنواع التعلم.\n\nالتعلم الموجه supervised.\nالتعلم غير الموجه.\n\n"
                                 "ملاحظات المحاضر: اشرح الفرق بمثال من الحياة اليومية.")
        assert "ملاحظات" not in to_speech_text(doc.page(2), include_notes=False)[0].text
        assert units[2].text.endswith("جدول، عدد صفوفه 2.\nالنوع: موجه، مثال: تصنيف الصور.\n"
                                      "النوع: غير موجه، مثال: التجميع.")
        page = doc.page(2)
        page.blocks[2].image["description"] = "رسم يوضح أنواع التعلم"
        assert "صورة: رسم يوضح أنواع التعلم." in to_speech_text(page)[0].text
    cfg.xlsx_preview_rows = 2
    with open_document(xlsx_file, cfg) as doc:
        unit = to_speech_text(doc.page(1))[0]
        assert unit.sheet == "الدرجات" and "جدول، عدد صفوفه 120، وهذه أول 2 منها:" in unit.text


# --- CLI ---------------------------------------------------------------------------------

def test_cli_outline_page_json_and_errors(pdf_file, xlsx_file, tmp_path, capsys):
    assert main(["extract", str(pdf_file), "--outline"]) == 0
    out = capsys.readouterr().out
    assert "File type: pdf   pages: 4   images: 2   tables: 1" in out
    assert "NEEDS OCR: pages 4" in out and "- Results  (page 3)" in out
    assert main(["extract", str(pdf_file), "--page", "2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("--- page 2 ---") and f"[paragraph] [ar] {AR_RIGHT}" in out
    assert "File type" not in out                                  # no full scan for one page
    assert main(["extract", str(pdf_file), "--page", "3", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pages"][0]["blocks"][1]["kind"] == "table" and data["pages"][0]["blocks"][1]["page"] == 3
    assert main(["extract", str(xlsx_file), "--page", "الدرجات", "--rows", "2:2", "--json"]) == 0
    assert [r["الاسم"] for r in json.loads(capsys.readouterr().out)] == ["طالب 2", "طالب 3"]
    assert main(["extract", str(pdf_file), "--page", "2", "--speech"]) == 0
    assert f"{AR_HEADING}.\n\n{AR_RIGHT}" in capsys.readouterr().out
    old = tmp_path / "old.ppt"
    old.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "PowerPoint Document".encode("utf-16-le"))
    assert main(["extract", str(old)]) == 1
    assert main(["extract", str(pdf_file), "--page", "9"]) == 1
    err = capsys.readouterr().err
    assert "Error: PowerPoint 97-2003 (.ppt)" in err and "page 9 does not exist" in err


def test_cli_full_extract_and_no_images(docx_file, tmp_path, capsys):
    assert main(["extract", str(docx_file), "--no-images"]) == 0
    out = capsys.readouterr().out
    assert "Title: مقدمة في الذكاء الاصطناعي" in out and "--- page 2 ---" in out
    assert "[heading1] [ar] مقدمة في الذكاء الاصطناعي" in out and "[image] 200x150" in out
    assert not (tmp_path / "images").exists()
