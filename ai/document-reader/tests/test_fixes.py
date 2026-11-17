"""One test per problem found on the real sample files (numbers match the problem list).

Every document is generated here; the real files in ai/samples-in are never used.
Arabic text in PDFs avoids the letter lam (see conftest.py).
"""
import pytest

from conftest import png
from reader import open_document, to_speech_text
from reader.lang import clean_text
from reader.model import Block


def kinds(page):
    return [(b.kind, b.text) for b in page.blocks]


# --- 1. Arabic PDF tables came out reversed, columns left to right ----------------------------

@pytest.fixture
def pdf_arabic_table(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_htmlbox(pymupdf.Rect(100, 40, 500, 90), '<h1 dir="rtl">مقارنة</h1>')
    x0, y0, w, h = 150, 120, 150, 40
    for r in range(4):
        page.draw_line((x0, y0 + r * h), (x0 + 2 * w, y0 + r * h))
    for c in range(3):
        page.draw_line((x0 + c * w, y0), (x0 + c * w, y0 + 3 * h))
    # right column is the first one when read right to left
    cells = [("معيار", "نتيجة"), ("سرعة", "جيدة"), ("دقة", "ممتازة")]
    for r, (right, left) in enumerate(cells):
        for col, text in ((1, right), (0, left)):
            rect = pymupdf.Rect(x0 + col * w + 5, y0 + r * h + 8, x0 + (col + 1) * w - 5, y0 + (r + 1) * h - 5)
            page.insert_htmlbox(rect, f'<p dir="rtl">{text}</p>')
    path = tmp_path / "ar_table.pdf"
    doc.save(str(path))
    return path


def test_1_pdf_arabic_table_logical_order_and_rtl_columns(pdf_arabic_table, cfg):
    with open_document(pdf_arabic_table, cfg) as doc:
        tables = [b for b in doc.page(1).blocks if b.kind == "table"]
    assert len(tables) == 1
    assert tables[0].table["columns"] == ["معيار", "نتيجة"]
    assert tables[0].table["rows"] == [["سرعة", "جيدة"], ["دقة", "ممتازة"]]
    assert tables[0].text == "معيار: سرعة، نتيجة: جيدة\nمعيار: دقة، نتيجة: ممتازة"


# --- 2 and 10. Excel: title row taken as header; charts and formulas unreported ---------------

@pytest.fixture
def xlsx_titled(tmp_path):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    wb = Workbook()
    ws = wb.active
    ws.title = "علامات الطلاب"
    ws.sheet_view.rightToLeft = True
    ws["A1"] = "جدول علامات وهمي – 5 طلاب"
    ws.merge_cells("A1:E1")
    ws.append([])
    ws.append(["اسم الطالب", "الرياضيات", "العلوم", "اللغة العربية", "المعدل"])
    for i, (name, a, b, c) in enumerate([("أحمد", 80, 90, 70), ("سارة", 95, 85, 90), ("عمر", 60, 75, 80),
                                         ("ليان", 88, 92, 81), ("يزن", 70, 65, 90)], start=4):
        ws.append([name, a, b, c, f"=AVERAGE(B{i}:D{i})"])
    ws["H12"] = "البيانات افتراضية للتدريب"
    ws.merge_cells("H12:K12")
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=2, min_row=3, max_row=8), titles_from_data=True)
    ws.add_chart(chart, "H3")
    path = tmp_path / "titled.xlsx"
    wb.save(str(path))
    return path


def test_2_xlsx_header_below_a_title_row(xlsx_titled, cfg):
    with open_document(xlsx_titled, cfg) as doc:
        sheet = doc.info.sheets[0]
        assert sheet.columns == ["اسم الطالب", "الرياضيات", "العلوم", "اللغة العربية", "المعدل"]
        assert (sheet.header_row, sheet.row_count, sheet.title) == (3, 5, "جدول علامات وهمي – 5 طلاب")
        rows = list(doc.rows(1, 1, 2))
        assert rows[0]["اسم الطالب"] == "أحمد" and rows[0]["العلوم"] == "90" and len(rows[0]) == 5
        page = doc.page(1)
        assert ("paragraph", "جدول علامات وهمي – 5 طلاب") in kinds(page)
        table = next(b for b in page.blocks if b.kind == "table")
        assert table.table["columns"] == sheet.columns and len(table.table["rows"]) == 5
        assert table.text.split("\n")[1] == "اسم الطالب: سارة، الرياضيات: 95، العلوم: 85، اللغة العربية: 90"


def test_10_xlsx_charts_and_formulas_without_values_are_reported(xlsx_titled, cfg):
    with open_document(xlsx_titled, cfg) as doc:
        warnings = " | ".join(doc.info.warnings)
    assert "1 chart" in warnings and "not read" in warnings
    assert "المعدل" in warnings and "formulas" in warnings and "saved" in warnings


# --- 3. Space before Arabic diacritics split words --------------------------------------------

def test_3_space_before_diacritics_is_removed():
    assert clean_text("منصة ومهي ّأة للطلبة") == "منصة ومهيّأة للطلبة"
    assert clean_text("كلما قل ّت") == "كلما قلّت"
    assert clean_text("المضي قدما ً إذا") == "المضي قدماً إذا"
    assert clean_text("شَجَرَةُ الزَّيْتُون") == "شَجَرَةُ الزَّيْتُون"


def test_3_tanween_extracted_before_the_line_goes_back_to_the_last_word():
    from reader.lang import fix_leading_marks
    assert fix_leading_marks("ًيحوّل بنود المذكرة إلى خدمات يستخدمها الطلبة يوميا") == \
        "يحوّل بنود المذكرة إلى خدمات يستخدمها الطلبة يومياً"
    assert fix_leading_marks("نص عادي") == "نص عادي" and fix_leading_marks("") == ""


# --- 4. One-cell 'tables' (call-out boxes) were tables; speech said "0 rows" ---------------

def test_4_one_cell_table_is_read_as_paragraphs(tmp_path, cfg):
    import docx
    d = docx.Document()
    d.add_paragraph("Intro text.")
    cell = d.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = "A global snapshot"
    cell.add_paragraph("In 2022, there were 20 million new cases.")
    d.save(str(tmp_path / "box.docx"))
    with open_document(tmp_path / "box.docx", cfg) as doc:
        page = doc.page(1)
        assert kinds(page) == [("paragraph", "Intro text."), ("paragraph", "A global snapshot"),
                               ("paragraph", "In 2022, there were 20 million new cases.")]
        assert doc.info.table_count == 0
        assert "Table" not in to_speech_text(page)[0].text


def test_4_speech_never_announces_an_empty_table():
    block = Block("table", "Only; header", "en", 1, table={"columns": ["Only", "header"], "rows": []})
    assert "0 rows" not in to_speech_text([block])[0].text


# --- 5 and 6. Slides without a title placeholder; number-only notes ----------------------------

@pytest.fixture
def pptx_textbox_titles(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    blank = prs.slide_layouts[6]

    def box(slide, left, top, text, size):
        frame = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(4), Inches(1)).text_frame
        frame.text = text
        frame.paragraphs[0].runs[0].font.size = Pt(size)

    s1 = prs.slides.add_slide(blank)                     # cover: two big lines
    box(s1, 1, 2, "الفصل الثاني", 44)
    box(s1, 1, 3, "قاعدة الطباق والمقابلة", 40)
    s1.notes_slide.notes_text_frame.text = "1"
    s2 = prs.slides.add_slide(blank)                     # title as a big text box
    box(s2, 5, 3, "شرح الطباق بالتفصيل الكامل مع أمثلة من القرآن الكريم والشعر العربي القديم", 18)
    box(s2, 5, 1, "ما هو الطباق؟", 40)
    s2.notes_slide.notes_text_frame.text = "اذكر مثالاً من الحياة اليومية."
    s3 = prs.slides.add_slide(blank)                     # two equal small boxes: no title
    box(s3, 1, 1, "نص أول طويل نسبياً يشرح الفكرة الأولى بالتفصيل للطلاب في هذه المحاضرة", 18)
    box(s3, 5, 1, "نص ثان طويل نسبياً يشرح الفكرة الثانية بالتفصيل للطلاب في هذه المحاضرة", 18)
    s3.notes_slide.notes_text_frame.text = "  3 . "
    path = tmp_path / "boxes.pptx"
    prs.save(str(path))
    return path


def test_5_largest_text_box_is_the_slide_title(pptx_textbox_titles, cfg):
    with open_document(pptx_textbox_titles, cfg) as doc:
        assert doc.page(2).blocks[0].kind == "heading" and doc.page(2).blocks[0].text == "ما هو الطباق؟"
        assert doc.page(1).blocks[0].text == "الفصل الثاني" and doc.page(1).blocks[0].level == 1
        assert all(b.kind != "heading" for b in doc.page(3).blocks)
        info = doc.info
    assert [(e.title, e.unit) for e in info.outline] == [("الفصل الثاني", 1), ("ما هو الطباق؟", 2)]
    assert any("slide 3" in w and "no title" in w for w in info.warnings)


def test_6_notes_without_letters_are_dropped(pptx_textbox_titles, cfg):
    with open_document(pptx_textbox_titles, cfg) as doc:
        notes = [(p.unit, b.text) for p in doc.pages() for b in p.blocks if b.kind == "notes"]
    assert notes == [(2, "اذكر مثالاً من الحياة اليومية.")]


# --- 7. Full-page background images counted as content ---------------------------------------

def test_7_full_page_background_is_skipped_but_scans_keep_their_image(tmp_path, cfg):
    import pymupdf
    doc = pymupdf.open()
    slide = doc.new_page()
    slide.insert_image(slide.rect, stream=png(800, 1000, (240, 240, 250)))
    slide.insert_htmlbox(pymupdf.Rect(50, 50, 550, 300), "<h1>Title</h1><p>Some real text on the slide.</p>")
    slide.insert_image(pymupdf.Rect(100, 400, 300, 550), stream=png(200, 150))
    scan = doc.new_page()
    scan.insert_image(scan.rect, stream=png(600, 800, (200, 200, 200)))
    doc.save(str(tmp_path / "bg.pdf"))
    with open_document(tmp_path / "bg.pdf", cfg) as reader:
        assert [b.image["width"] for b in reader.page(1).blocks if b.kind == "image"] == [200]
        assert reader.page(2).needs_ocr and [b.kind for b in reader.page(2).blocks] == ["image"]
        info = reader.info
    assert info.image_count == 2
    assert any("background" in w for w in info.warnings)


# --- 8. A sentence wrapped onto two lines became two paragraphs ------------------------------

def test_8_wrapped_lines_are_joined_into_one_paragraph(tmp_path, cfg):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    css = "p{font-size:12px; margin:0}"
    # one sentence wrapped onto two lines; MuPDF reports each line as its own block
    for top, text in ((100, "مساعدات دراسية ذكية"), (114, "تخدم ذوي حاجات خاصة")):
        page.insert_htmlbox(pymupdf.Rect(300, top, 550, top + 16), f'<p dir="rtl">{text}</p>', css=css)
    doc.save(str(tmp_path / "wrap.pdf"))
    with open_document(tmp_path / "wrap.pdf", cfg) as reader:
        assert kinds(reader.page(1)) == [("paragraph", "مساعدات دراسية ذكية تخدم ذوي حاجات خاصة")]


def test_8_join_rule_keeps_separate_paragraphs_apart():
    # MuPDF decides by itself which generated lines share a block, so the cases that must NOT be
    # joined are checked on the rule directly: (bbox x0, y0, x1, y1), font size
    from reader.pdf_reader import PdfDocument

    def join(first, second, box1, box2, size1=12.0, size2=12.0):
        a, b = Block("paragraph", first, "ar", 1), Block("paragraph", second, "ar", 1)
        sizes = {id(a): (box1, size1), id(b): (box2, size2)}
        return [x.text for x in PdfDocument._join_wrapped([a, b], sizes, 1)]

    line1, line2 = (451, 97, 549, 119), (441, 111, 549, 133)         # measured from the PDF above
    assert join("سطر أول", "سطر ثان", line1, line2) == ["سطر أول سطر ثان"]
    assert join("انتهت جملة.", "جملة جديدة", line1, line2) == ["انتهت جملة.", "جملة جديدة"]
    assert join("نص", "عنوان كبير", line1, line2, 12, 18) == ["نص", "عنوان كبير"]          # size
    assert join("سطر", "بعيد", line1, (441, 160, 549, 182)) == ["سطر", "بعيد"]           # far below
    assert join("سطر", "عمود آخر", line1, (100, 111, 200, 133)) == ["سطر", "عمود آخر"]  # other column
    assert join("نفس السطر", "تكملة", line1, (300, 98, 440, 118)) == ["نفس السطر", "تكملة"]  # same line
    # one name per line with space between the lines (a list, not a wrapped sentence)
    assert join("اسم أول وتخصصه", "اسم ثان وتخصصه", (585, 356, 896, 372), (660, 385, 896, 402),
                16.0, 16.8) == ["اسم أول وتخصصه", "اسم ثان وتخصصه"]


# --- 9. PDF headings judged per page; file-name metadata used as the title -------------------

@pytest.fixture
def pdf_slides(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    cover = doc.new_page()
    cover.insert_text((72, 200), "Chapter 1", fontsize=47)
    cover.insert_text((72, 280), "Information Security", fontsize=34)
    for title in ("Learning Objectives", "Confidentiality"):
        page = doc.new_page()
        page.insert_text((72, 80), title, fontsize=34)
        for i in range(4):
            page.insert_text((72, 150 + 40 * i), f"Point {i + 1} explained in a full sentence here.", fontsize=22)
    path = tmp_path / "Ch 1_5e7cf8dcf4cde52e80cc9670ce63e3a6.pdf"
    doc.set_metadata({"title": path.stem})
    doc.save(str(path))
    return path


def test_9_pdf_headings_use_document_body_size_and_title_skips_file_name(pdf_slides, cfg):
    with open_document(pdf_slides, cfg) as doc:
        cover = doc.page(1)
        assert [(b.kind, b.level, b.text) for b in cover.blocks] == [
            ("heading", 1, "Chapter 1"), ("heading", 2, "Information Security")]
        info = doc.info
    assert info.title == "Chapter 1 - Information Security"
    assert [(e.title, e.unit, e.level) for e in info.outline] == [
        ("Chapter 1", 1, 1), ("Information Security", 1, 2), ("Learning Objectives", 2, 2),
        ("Confidentiality", 3, 2)]


# --- warning for what cannot be repaired: reversed Arabic without presentation forms ---------

def test_reversed_arabic_that_cannot_be_repaired_is_reported(tmp_path, cfg):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    # stored letter by letter in reverse ('محاضرة جديدة سريعة ممتازة' drawn backwards)
    page.insert_htmlbox(pymupdf.Rect(50, 50, 550, 120), "<p>ةزاتمم ةعيرس ةديدج ةرضاحم ةديدج ةرضاحم</p>")
    doc.save(str(tmp_path / "reversed.pdf"))
    with open_document(tmp_path / "reversed.pdf", cfg) as reader:
        assert any("reversed" in w for w in reader.page(1).warnings)
        assert any("reversed" in w for w in reader.info.warnings)
