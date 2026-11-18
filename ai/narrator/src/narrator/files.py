"""Narrating a lecture file (read with the document-reader module) with guidance phrases."""
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import NarratorConfig
from .dates import say_until, say_when
from .errors import ReaderUnavailableError
from .segments import Segment
from .words import count, join, number, ordinal, sentence, sentences

_NUMERIC = re.compile(r"[-+−]?(?:\d+(?:[.,]\d+)?|[.,]\d+)%?")
UNIT_AR = {"page": ("صفحة", "f"), "slide": ("سلايد", "m"), "sheet": ("ورقة", "f")}
UNIT_EN = {"page": "page", "slide": "slide", "sheet": "sheet"}
TYPE_AR = {"pptx": "عرض تقديمي PowerPoint", "pdf": "ملف PDF", "docx": "مستند Word",
           "xlsx": "ملف Excel"}
TYPE_EN = {"pptx": "a PowerPoint presentation", "pdf": "a PDF file", "docx": "a Word document",
           "xlsx": "an Excel workbook"}


def load_reader(config: NarratorConfig):
    """The document-reader package (ai/document-reader/src is added to the path if needed)."""
    path = str(Path(config.reader_path))
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import reader
        return reader
    except Exception as exc:
        raise ReaderUnavailableError(f"document-reader not found at {path} (NARRATOR_READER_PATH): {exc}") from exc


@dataclass
class FileNarration:
    """intro, then the segments of each page/slide/sheet, then the outro."""
    intro: Segment
    units: List[List[Segment]]
    outro: Segment
    unit_type: str
    unit_numbers: List[int]                 # unit number of each entry in units
    topics: List[Dict[str, Any]]            # [{"number", "title", "unit"}]
    lang: str
    sheets: List[Optional[str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def segments(self) -> List[Segment]:
        return [self.intro] + [s for unit in self.units for s in unit] + [self.outro]

    def navigator(self):
        from .navigation import Navigator
        return Navigator(self)


class FileNarrator:
    def __init__(self, config: Optional[NarratorConfig] = None):
        self.config = (config or NarratorConfig.from_env()).validate()
        self.lang = self.config.phrase_language
        self.reader = load_reader(self.config)

    # --- public ------------------------------------------------------------------------
    def narrate(self, path, meta: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None,
                describe: bool = False, describer=None, reader_config=None,
                units: Optional[Iterable[int]] = None) -> FileNarration:
        """meta (from the platform, all optional): course, instructor, uploaded_at, title.

        describe=True runs the phase-2 image describer (images are sent to Google); describer
        can be an ImageDescriber prepared by the caller (tests inject one with a fake engine).
        units: the pages/slides that will be read; only their images are described (every
        unit is still narrated, so navigation works across the whole file).
        """
        meta = meta or {}
        now = now or self.config.now()
        warnings: List[str] = []
        with self.reader.open_document(path, reader_config) as doc:
            info = doc.info
            pages = list(doc.pages())
        warnings += info.warnings
        if describe or describer is not None:
            describer = describer or self.reader.ImageDescriber(language=self.config.language)
            wanted = set(units) if units is not None else None
            warnings += describer.describe_pages([p for p in pages if wanted is None or p.unit in wanted])
        topics = self._topics(info, pages[0] if pages else None)
        starts = {t["unit"]: t for t in topics}
        units, current = [], None
        for page in pages:
            current = starts.get(page.unit, current)
            units.append(self._page(page, info.unit_count, current, len(topics), starts.get(page.unit)))
        words = sum(len(s.text.split()) for unit in units for s in unit)
        intro = self._intro(info, meta, now, topics, words)
        return FileNarration(intro=intro, units=units, outro=self._outro(info.unit_type, bool(topics)),
                             unit_type=info.unit_type, unit_numbers=[p.unit for p in pages], topics=topics,
                             lang=self.lang, sheets=[p.sheet for p in pages], warnings=warnings)

    # --- parts -------------------------------------------------------------------------
    @staticmethod
    def is_title_page(page) -> bool:
        """A first page/slide with only a title, or a title and a subtitle (images allowed).

        Its heading is the name of the file, not a topic. A subtitle is a short phrase; a full
        sentence (ending in . ! ? :) means the slide already teaches something.
        """
        if page is None or page.unit != 1:
            return False
        texts = [b for b in page.blocks if b.kind not in ("image",)]
        if not texts or len(texts) > 2 or any(b.kind not in ("heading", "paragraph") for b in texts):
            return False
        if not any(b.kind == "heading" for b in texts):
            return False
        return all(len(b.text) <= 80 and not b.text.strip().endswith(tuple(".!?؟:")) for b in texts)

    @classmethod
    def _topics(cls, info, first_page=None) -> List[Dict[str, Any]]:
        topics, last = [], None
        skip_first = cls.is_title_page(first_page)
        for entry in info.outline:
            title = " ".join(entry.title.split())
            if skip_first and entry.unit == 1:
                continue                                    # the title slide is not a topic
            if entry.level == 1 and title and title != last:
                topics.append({"number": len(topics) + 1, "title": title, "unit": entry.unit})
                last = title
        return topics

    def _unit_word(self, unit_type: str) -> str:
        return UNIT_EN[unit_type] if self.lang == "en" else UNIT_AR[unit_type][0]

    def _intro(self, info, meta, now, topics, words) -> Segment:
        en, tz = self.lang == "en", self.config.tz()
        course, instructor = meta.get("course"), meta.get("instructor")
        title = meta.get("title") or info.title
        if en:
            source = (f"A file from the course {course}" if course else "A file" if instructor else "") + \
                     (f", {instructor}" if course and instructor else f" from {instructor}" if instructor else "")
        else:
            source = (f"ملف من مساق {course}" if course else "ملف" if instructor else "") + \
                     (f"، {instructor}" if course and instructor else f" من {instructor}" if instructor else "")
        uploaded = None
        if meta.get("uploaded_at"):
            when = say_when(meta["uploaded_at"], self.lang, tz, now, "uploaded_at")
            ago = say_until(meta["uploaded_at"], self.lang, tz, now, "uploaded_at")
            uploaded = f"Uploaded {when}, {ago}" if en else f"تاريخ الرفع: {when}، {ago}"
        units = count(info.unit_count, info.unit_type, self.lang)
        kind = (f"Type: {TYPE_EN.get(info.file_type, info.file_type)} with {units}" if en else
                f"النوع: {TYPE_AR.get(info.file_type, info.file_type)} من {units}")
        parts = [source, uploaded, (f"Title: {title}" if en else f"العنوان: {title}") if title else None, kind]
        if topics:
            shown = [t["title"] for t in topics[:self.config.max_topics_listed]]
            rest = len(topics) - len(shown)
            listed = join(shown, self.lang)
            if rest:
                if en:
                    listed += f", and {rest} more"
                else:
                    listed += "، و" + {1: "موضوع آخر", 2: "موضوعين آخرين"}.get(rest, f"{count(rest, 'topic', 'ar')} أخرى")
            parts.append(f"It covers {count(len(topics), 'topic', 'en')}: {listed}" if en else
                         f"يتناول {count(len(topics), 'topic', 'ar')}: {listed}")
        items = [count(n, noun, self.lang) for n, noun in
                 ((info.image_count, "image"), (info.table_count, "table"), (info.chart_count, "chart")) if n]
        if en:
            parts.append(f"It has {' and '.join(items)}" if items else "It has no images or tables")
        else:
            parts.append(f"ويحتوي على {' و'.join(items)}" if items else "ولا يحتوي على صور أو جداول")
        minutes = math.ceil(words / self.config.words_per_minute)
        if en:
            parts.append(f"Estimated listening time: about {count(minutes, 'minute', 'en')}" if minutes
                         else "Estimated listening time: less than a minute")
        else:
            parts.append(f"مدة الاستماع التقديرية حوالي {count(minutes, 'minute', 'ar', one=False)}" if minutes
                         else "مدة الاستماع التقديرية أقل من دقيقة")
        return Segment(sentences(parts), "intro", {"unit_type": info.unit_type, "unit_count": info.unit_count,
                                                   "topic_count": len(topics)})

    def _outro(self, unit_type: str, has_topics: bool) -> Segment:
        if self.lang == "en":
            unit = UNIT_EN[unit_type]
            options = [f"listen again from the beginning", f"go back to the previous {unit}", f"go to a {unit}"]
            if has_topics:
                options.append("go to a topic")
            text = f"End of file. Options: {', '.join(options[:-1])}, or {options[-1]}."
        else:
            word, gender = UNIT_AR[unit_type]
            chosen = "معيّنة" if gender == "f" else "معيّن"
            previous = "السابقة" if gender == "f" else "السابق"
            options = ["الاستماع من البداية", f"الرجوع إلى {self._def(word)} {previous}", f"الذهاب إلى {word} {chosen}"]
            if has_topics:
                options.append("الذهاب إلى موضوع معيّن")
            text = f"انتهى الملف. الخيارات المتاحة: {'، '.join(options[:-1])}، أو {options[-1]}."
        return Segment(text, "outro", {"unit_type": unit_type})

    @staticmethod
    def _def(word: str) -> str:
        return f"ال{word}"

    def _page(self, page, unit_count: int, topic, topic_count: int, starts) -> List[Segment]:
        en = self.lang == "en"
        title = next((b.text for b in page.blocks if b.kind == "heading" and b.text.strip()), "")
        if page.unit_type == "sheet":
            title = page.sheet or title
        title = " ".join(title.split())
        pos = {"unit": page.unit, "unit_type": page.unit_type, "unit_count": unit_count,
               "topic": topic["number"] if topic else None, "topic_count": topic_count}
        if page.sheet is not None:
            pos["sheet"] = page.sheet
        out: List[Segment] = []
        said_title = False
        if starts:
            n = starts["number"]
            if en:
                head = f"Topic {n} of {topic_count}: {starts['title']}"
            else:
                head = f"الموضوع {ordinal(n, 'ar') or n} من {topic_count}: {starts['title']}"
            out.append(Segment(sentence(head), "topic_change", dict(pos)))
            said_title = starts["title"] == title
        word = self._unit_word(page.unit_type)
        where = f"{word.capitalize() if en else word} {page.unit} {'of' if en else 'من'} {unit_count}"
        if title and not said_title:
            where += f": {title}"
        out.append(Segment(sentence(where), "position", dict(pos)))
        spoken_title = bool(title)
        for index, block in enumerate(page.blocks):
            if block.kind == "heading" and spoken_title and " ".join(block.text.split()) == title:
                continue                                    # already said (also repeated titles)
            if block.kind == "table" and block.table:
                out += self._table(block.table, dict(pos, block=index))
            elif block.kind == "image":
                out += self._image(block, dict(pos, block=index))
            else:
                text = self.reader.speech.block_speech(block)
                kind = {"heading": "heading", "list": "list", "notes": "notes", "chart": "chart"}.get(block.kind, "content")
                if text.strip():
                    out.append(Segment(text, kind, dict(pos, block=index)))
        return out

    def _table(self, table: Dict[str, Any], pos: Dict[str, Any], source: str = "file") -> List[Segment]:
        en = self.lang == "en"
        columns = [c for c in table.get("columns") or []]
        rows = table.get("rows") or []
        total = table.get("total_rows", len(rows))
        names = join(columns, self.lang)
        cols = count(len(columns), "column", self.lang)
        pos = dict(pos, source=source)
        if columns and all(_NUMERIC.fullmatch(str(c).strip()) for c in columns):
            # The "header" is numbers (e.g. a z-table photographed without its header row):
            # it is a data row, so the rows are read as values, without column names.
            return self._plain_table([columns] + rows, total + 1, pos)
        if not total:
            text = (f"Table with {cols} and no rows. Columns: {names}." if en else
                    f"جدول من {cols} بدون صفوف. الأعمدة: {names}.")
            return [Segment(text, "table", pos)]
        intro = (f"Table with {cols} and {count(total, 'row', 'en')}. Columns: {names}." if en else
                 f"جدول من {cols} و{count(total, 'row', 'ar')}. الأعمدة: {names}.")
        out = [Segment(intro, "table", dict(pos, rows=total))]
        table_text = self.reader.tables.table_text
        shown = rows[:self.config.max_table_rows]
        for i, row in enumerate(shown, 1):
            line = table_text({"columns": columns, "rows": [row]}) or " ".join(str(c) for c in row if c)
            if total >= self.config.number_rows_from:
                line = f"Row {i} of {total}: {line}" if en else f"الصف {i} من {total}: {line}"
            out.append(Segment(sentence(line), "table_row", dict(pos, row=i, rows=total)))
        rest = total - len(shown)
        if rest > 0:
            text = (f"{rest} more {'row is' if rest == 1 else 'rows are'} not read." if en else
                    f"لم تُقرأ بقية الصفوف، وعددها {number(rest)}.")
            out.append(Segment(text, "table", dict(pos, rows=total, unread=rest)))
        return out

    def _plain_table(self, rows: List[List[Any]], total: int, pos: Dict[str, Any]) -> List[Segment]:
        en = self.lang == "en"
        width = max(len(r) for r in rows)
        cols = count(width, "column", self.lang)
        intro = (f"Table with {cols} and {count(total, 'row', 'en')}, without column names." if en else
                 f"جدول من {cols} و{count(total, 'row', 'ar')}، بدون أسماء أعمدة.")
        out = [Segment(intro, "table", dict(pos, rows=total))]
        shown = rows[:self.config.max_table_rows]
        for i, row in enumerate(shown, 1):
            line = join([str(c) for c in row if str(c).strip()], self.lang)
            if total >= self.config.number_rows_from:
                line = f"Row {i} of {total}: {line}" if en else f"الصف {i} من {total}: {line}"
            out.append(Segment(sentence(line), "table_row", dict(pos, row=i, rows=total)))
        rest = total - len(shown)
        if rest > 0:
            out.append(Segment(f"{rest} more {'row is' if rest == 1 else 'rows are'} not read." if en else
                               f"لم تُقرأ بقية الصفوف، وعددها {number(rest)}.", "table", dict(pos, rows=total, unread=rest)))
        return out

    def _image(self, block, pos: Dict[str, Any]) -> List[Segment]:
        image = dict(block.image or {})
        if image.get("status") == "decorative":
            return []
        table = image.pop("table", None) if image.get("category") == "table" else None
        labels = self.reader.explain
        copy = self.reader.Block("image", block.text, block.lang, block.unit, block.unit_type, block.sheet, image=image)
        text = self.reader.speech.block_speech(copy).strip() if image.get("status") else ""
        en = self.lang == "en"
        auto = [l for l in set(labels.AUTO_LABEL.values()) if text.startswith(l)]
        if auto:
            rest = text[len(auto[0]):].strip()
            text = f"Image, automatic description: {rest}" if en else f"صورة، وصف تلقائي: {rest}"
        elif not text or image.get("status") == "undescribed":
            text = "Image without a description." if en else "صورة بدون وصف."
        pos = dict(pos, category=image.get("category"), status=image.get("status") or "undescribed")
        out = [Segment(text, "image", pos)]
        if table:
            out += self._table(table, pos, source="image")
        return out
