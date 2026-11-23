"""Builds small Arabic/English test documents of every supported type."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def png(width, height, color=(30, 120, 200)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for k in [k for k in os.environ if k.startswith("READER_") or k in ("GEMINI_API_KEY", "CB_EXPLAIN_LANGUAGE", "CB_GEMINI_IPV4")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("READER_IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("READER_DESCRIPTIONS_DIR", str(tmp_path / "descriptions"))
    monkeypatch.setenv("READER_ENV_FILE", str(tmp_path / "no.env"))     # never the real key
    monkeypatch.setenv("READER_OCR_DIR", str(tmp_path / "ocr"))

    def no_network(*args, **kwargs):
        raise AssertionError("test tried to reach Gemini; inject a fake vision engine")
    from google import genai
    monkeypatch.setattr(genai, "Client", no_network)


@pytest.fixture
def cfg(tmp_path):
    from reader import ReaderConfig
    return ReaderConfig(images_dir=str(tmp_path / "images"), descriptions_dir=str(tmp_path / "descriptions"),
                        env_file=str(tmp_path / "test.env"), ocr_dir=str(tmp_path / "ocr"))


@pytest.fixture
def docx_file(tmp_path):
    import docx
    from docx.shared import Inches
    (tmp_path / "photo.png").write_bytes(png(200, 150))
    (tmp_path / "icon.png").write_bytes(png(16, 16, (200, 0, 0)))
    d = docx.Document()
    d.add_heading("مقدمة في الذكاء الاصطناعي", level=1)
    d.add_paragraph("اليوم سنتحدث عن machine learning وكيف يتعلم الحاسوب من البيانات.")
    d.add_paragraph("النقطة الأولى", style="List Bullet")
    d.add_paragraph("النقطة الثانية", style="List Bullet")
    table = d.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("الاسم", "الدرجة"), ("أحمد", "90"), ("سارة", "85")]):
        table.cell(r, 0).text, table.cell(r, 1).text = a, b
    d.add_picture(str(tmp_path / "photo.png"), width=Inches(2))
    d.add_picture(str(tmp_path / "icon.png"))
    d.add_page_break()
    d.add_heading("Machine Learning Basics", level=1)
    d.add_heading("Supervised learning", level=2)
    d.add_paragraph("Models learn from labelled examples.")
    path = tmp_path / "lecture.docx"
    d.save(str(path))
    return path


@pytest.fixture
def pptx_file(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches
    logo, photo, icon = tmp_path / "logo.png", tmp_path / "photo.png", tmp_path / "icon.png"
    logo.write_bytes(png(100, 100, (0, 0, 0)))
    photo.write_bytes(png(300, 200))
    icon.write_bytes(png(20, 20, (255, 0, 0)))
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "مقدمة في تعلم الآلة"
    s1.placeholders[1].text = "المحاضرة الأولى"
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "أنواع التعلم"
    body = s2.placeholders[1].text_frame
    body.text = "التعلم الموجه supervised"
    body.add_paragraph().text = "التعلم غير الموجه"
    s2.shapes.add_picture(str(photo), Inches(6), Inches(5), Inches(3), Inches(2))
    s2.notes_slide.notes_text_frame.text = "اشرح الفرق بمثال من الحياة اليومية."
    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "مقارنة"
    left = s3.shapes.add_textbox(Inches(0.5), Inches(2), Inches(4), Inches(1))
    left.text_frame.text = "العمود الأيسر"
    right = s3.shapes.add_textbox(Inches(5.5), Inches(2), Inches(4), Inches(1))
    right.text_frame.text = "العمود الأيمن"
    rows = s3.shapes.add_table(3, 2, Inches(1), Inches(4), Inches(8), Inches(1.5)).table
    for r, (a, b) in enumerate([("النوع", "مثال"), ("موجه", "تصنيف الصور"), ("غير موجه", "التجميع")]):
        rows.cell(r, 0).text, rows.cell(r, 1).text = a, b
    s4 = prs.slides.add_slide(prs.slide_layouts[1])
    s4.shapes.title.text = "Summary"
    tf = s4.placeholders[1].text_frame
    tf.text = "Supervised learning uses labels"
    tf.add_paragraph().text = "Unsupervised learning finds groups"
    s4.shapes.add_picture(str(icon), Inches(0.1), Inches(0.1))
    for slide in (s1, s2, s3, s4):
        slide.shapes.add_picture(str(logo), Inches(9), Inches(0.1), Inches(0.8), Inches(0.8))
    path = tmp_path / "slides.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def xlsx_file(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "الدرجات"
    ws.sheet_view.rightToLeft = True
    ws.append(["الاسم", "الرقم الجامعي", "الدرجة"])
    for i in range(1, 121):
        ws.append([f"طالب {i}", 2020000 + i, 50 + i % 50])
    summary = wb.create_sheet("Summary")
    summary.append(["Course", "Students"])
    summary.append(["AI", 120])
    wb.create_sheet("Empty")
    wb.properties.title = "سجل الدرجات"
    path = tmp_path / "grades.xlsx"
    wb.save(str(path))
    return path


# Arabic in PDF fixtures avoids the letter lam: PDFs written by PyMuPDF's HTML engine map its
# ligature glyphs to wrong characters, which says nothing about real PDFs made by Word.
AR_HEADING = "محاضرة جديدة"
AR_RIGHT = "مرحبا بكم في محاضرة جديدة"
AR_LEFT = "شكرا"


@pytest.fixture
def pdf_file(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    logo, photo = png(80, 80, (0, 0, 0)), png(200, 150)
    p1 = doc.new_page()
    p1.insert_htmlbox(pymupdf.Rect(50, 40, 550, 300),
                      "<h1>Introduction to Machine Learning</h1>"
                      "<p>Machine learning lets computers learn from data.</p>"
                      "<ul><li>First idea</li><li>Second idea</li></ul>")
    p1.insert_image(pymupdf.Rect(100, 320, 300, 470), stream=photo)
    p2 = doc.new_page()
    p2.insert_htmlbox(pymupdf.Rect(50, 40, 550, 100), f'<h1 dir="rtl">{AR_HEADING}</h1>')
    p2.insert_htmlbox(pymupdf.Rect(320, 150, 550, 250), f'<p dir="rtl">{AR_RIGHT}</p>')
    p2.insert_htmlbox(pymupdf.Rect(50, 150, 280, 250), f'<p dir="rtl">{AR_LEFT}</p>')
    p3 = doc.new_page()
    p3.insert_text((72, 60), "Results", fontsize=20)
    cells = [["Model", "Accuracy"], ["CNN", "92"], ["SVM", "85"]]
    x, y, w, h = 72, 100, 150, 30
    for r in range(4):
        p3.draw_line((x, y + r * h), (x + 2 * w, y + r * h))
    for c in range(3):
        p3.draw_line((x + c * w, y), (x + c * w, y + 3 * h))
    for r, row in enumerate(cells):
        for c, value in enumerate(row):
            p3.insert_text((x + c * w + 8, y + r * h + 20), value, fontsize=11)
    p4 = doc.new_page()
    p4.insert_image(p4.rect, stream=png(600, 800, (230, 230, 230)))
    for page in doc:
        page.insert_image(pymupdf.Rect(520, 750, 580, 810), stream=logo)
    path = tmp_path / "notes.pdf"
    doc.save(str(path))
    doc.close()
    return path
