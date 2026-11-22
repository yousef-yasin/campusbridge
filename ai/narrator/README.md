# Narrator (CampusBridge AI)

Builds what a blind or visually impaired student hears around the content: guidance phrases
("سلايد 4 من 21: ...", "سؤال 2 من 10", "باقي 3 أيام") for lecture files, quizzes,
assignments, chat messages and notifications. The output is a list of **segments**, ready for the
`text-to-speech` module.

- **No AI.** Every phrase is a fixed template. (Image descriptions come from the
  document-reader's phase 2 when asked for; see below.)
- **Content keeps its language.** File text, question text, options, messages and names are
  read as written. Only the guidance phrases change language.
- **Language** follows the shared setting `CB_EXPLAIN_LANGUAGE` (the same one the
  document-reader uses): `ar` and `mixed` give Arabic phrases, `en` English ones.
- **Gender-neutral address.** No masculine or feminine forms of "you"; phrases use
  nouns and the passive voice ("هل يتم إرسال هذه الإجابة؟", "الإجابة كتابةً"). "عندك" is written
  without vowels.
- **Information from the platform** (course, instructor, upload date, deadlines, ...) is
  input. The narrator never invents it. When a piece is missing, it is left out of the
  sentence.
- **Dates** use Levantine month names and the weekday: «الأحد 15 تشرين الثاني». The year is said
  only when it is not the current year; today, tomorrow and yesterday are «اليوم», «غداً» and
  «أمس».
- **Times** are said naturally: «الساعة 9 ونصف صباحاً», «الساعة 11 و59 دقيقة مساءً»,
  «الساعة 12 منتصف الليل».
- **Time left** uses the same natural style: «باقي 3 أيام», «باقي ساعتين», «باقي يوم و5 ساعات»,
  «انتهى الموعد منذ يومين». Counted nouns follow Arabic number rules (ساعة واحدة، ساعتين، 3 ساعات،
  11 ساعة).

## Layout

```
narrator/
├── README.md
├── requirements.txt          # -r ../document-reader/requirements.txt, tzdata, pytest
├── examples/                 # fake platform data for trying the CLI
│   ├── file-meta.json  quiz.json  assignment.json  chat.json  notifications.json
├── src/narrator/
│   ├── __init__.py           # public API
│   ├── __main__.py           # CLI
│   ├── config.py             # NarratorConfig (NARRATOR_* env vars)
│   ├── errors.py             # NarratorError, ConfigError, InputError, ReaderUnavailableError
│   ├── segments.py           # Segment(text, kind, position), speech_text()
│   ├── words.py              # Arabic/English counting, ordinals, lists, option letters
│   ├── dates.py              # dates, times, durations, time left
│   ├── files.py              # lecture files (uses document-reader)
│   ├── navigation.py         # where am I / next / previous / repeat / go to
│   ├── common.py             # shared base for platform narrators
│   ├── quiz.py  assignment.py  chat.py  notifications.py
└── tests/                    # exact-text tests in Arabic and English (generated files only)
```

## Installation

Python 3.12, from `ai/narrator`:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

The narrator imports the document-reader from `ai/document-reader/src`. Use
`NARRATOR_READER_PATH` to point it elsewhere.

## Usage

CLI (run from `ai/narrator` with `src` on the path: PowerShell `$env:PYTHONPATH="src"`, bash
`export PYTHONPATH=src`):

```bash
python -m narrator file ../samples-in/CLT.pptx --meta examples/file-meta.json --units 1-3
python -m narrator file lecture.pdf --course "الإحصاء" --instructor "د. ليال الزبن" --uploaded-at 2026-11-15
python -m narrator file lecture.pptx --describe          # image descriptions (sent to Google)
python -m narrator quiz examples/quiz.json               # intro and all questions
python -m narrator quiz examples/quiz.json --question 2
python -m narrator quiz examples/quiz.json --confirm 1 ب   # option letter, index or written text
python -m narrator quiz examples/quiz.json --warning 5
python -m narrator assignment examples/assignment.json
python -m narrator chat examples/chat.json
python -m narrator notifications examples/notifications.json
python -m narrator --lang en --now 2026-11-18T12:00 --json notifications examples/notifications.json
```

`--now` fixes the current time, which is used for time left. `--json` prints the segments as
JSON. Errors print `error: ...` and exit with code 2.

```python
from narrator import FileNarrator, QuizNarrator, NotificationNarrator, speech_text

narration = FileNarrator().narrate("CLT.pptx", {"course": "الإحصاء", "instructor": "د. ليال الزبن",
                                                "uploaded_at": "2026-11-15T10:00:00+03:00"})
for segment in narration.segments:          # Segment(text, kind, position)
    print(segment.kind, segment.text)
audio_text = speech_text(narration.segments)   # one text for text-to-speech

nav = narration.navigator()                  # one per open file in the frontend
nav.next(); nav.previous(); nav.repeat(); nav.where_am_i(); nav.go_to(4); nav.go_to_topic(2)

quiz = QuizNarrator(quiz_json)
quiz.intro(); quiz.question(2); quiz.confirm(2, "ب"); quiz.confirm_submit({1: 0, 2: "ب"})
quiz.warnings_due(ends_at)                  # call periodically: 5- and 1-minute warnings, once each
```

## Segments

`Segment.kind` is one of the following:

| Group | Kinds |
|---|---|
| Files | `intro`, `topic_change`, `position`, `heading`, `content`, `list`, `notes`, `chart`, `image`, `table`, `table_row`, `outro` |
| Quiz | `intro`, `position`, `question`, `options`, `confirm`, `time_warning` |
| Assignment | `assignment` (with `position.part`: title, due, description, attachments, submission) |
| Chat and notifications | `summary`, `message`, `notification`, `emergency` (with `position.priority: "high"`) |
| Navigation answers | `navigation` |

`position` says where a segment belongs. For files that is `unit`, `unit_type`, `unit_count`,
`topic`, `topic_count`, `block`, and for tables also `row`, `rows` and `source` (file or image).
For a quiz it is `question` and `questions`.

## Files

**Intro.** Each part below is a sentence, and a part whose information is missing is left out:

- course and instructor;
- upload date, with how long ago;
- title;
- type, with the number of pages, slides or sheets;
- number of topics, naming the first 5 (`NARRATOR_MAX_TOPICS`) and then «و X مواضيع أخرى»;
- number of useful images (decorative ones are not counted), tables and charts;
- estimated listening time (`NARRATOR_WORDS_PER_MINUTE`, default 130). It does not depend on which
  images were described in this run: image text is left out, and each useful image counts as
  `NARRATOR_WORDS_PER_IMAGE` (25) words.

Descriptions already in the document-reader cache are used for every page, without any network
call, so an image found decorative once is skipped and not counted afterwards. An image that was
never described counts as useful.

**Topics** come from the document-reader outline (level-1 headings, or slide titles), with
repeated titles merged. A **title slide** is not a topic: the first page or slide counts as one
when it has only a title, or a title and a short subtitle (images allowed). A subtitle is a
phrase of at most 80 characters that does not end like a sentence (. ! ? :). Such a slide
gets no «الموضوع ...» announcement and is not counted in the intro.

**Per page or slide:** «سلايد 4 من 21: العنوان». When a new topic starts here, it is announced
first: «الموضوع الثاني من 15: ...». The title is then not repeated.

**Tables:**
- First: «جدول من 3 أعمدة و8 صفوف. الأعمدة: ...».
- Then the rows. A table with at least `NARRATOR_NUMBER_ROWS_FROM` (4) rows numbers them: «الصف 2 من 8: ...».
- At most `NARRATOR_MAX_TABLE_ROWS` (10) rows are read, then «لم تُقرأ بقية الصفوف، وعددها N».
- A table found inside an image is read the same way.
- When every column name is a number, the "header" is really a data row (seen on a photographed z-table). The table is then read without column names: «جدول من 11 عموداً و4 صفوف، بدون أسماء أعمدة».

**Images:**
- «صورة، وصف تلقائي: ...», from the phase-2 description.
- «صورة: ...» for a manual description.
- «صورة بدون وصف» when there is no description.
- Decorative images are skipped.
- When a description's numbers failed the check (`needs_review`), the document-reader's rule
  applies: those sentences are dropped and the numbers are read from the image text.
- Descriptions are made only with `--describe` (or `describe=True`), and they use the
  document-reader's cache. Only the images of the requested pages are described (`--units`,
  or `units=` in Python). The other pages are still narrated, so navigation works. **Images are then sent to Google**; see the document-reader README.

**Summaries and questions.** These come from `ai/lecture-summarization` and
`ai/question-generation`. **Text is sent to Google.**
- `--summaries` (`summaries=True`) reads a page summary right after each requested page, as a
  segment of kind `page_summary`: «ملخص تلقائي: …» and the key points.
- `--questions` (`questions=True`) makes practice questions. `read_summaries=False` makes the
  summaries without reading them after each page.
- `Navigator.summarize()` («لخّصلي الصفحة») returns the current page's summary. At the intro or
  the end it returns the file summary.
- `Navigator.ask_me(wait_seconds=8)` («اسألني») returns three segments: `question`, then `wait`
  (the frontend pauses for `position.seconds` or until the student is ready), then `answer`. Each
  call asks the next question of the page.
- Without summaries or questions, these return «لا يوجد ملخص متاح هنا.» or
  «لا توجد أسئلة متاحة هنا.».

**Scanned pages and photos (OCR).** With `--ocr` (or `ocr=True`), the requested pages that need
OCR are read with the document-reader's phase 4. **Page images are sent to Google**, with
Tesseract as the local fallback.
- Right after «صفحة 2 من 9» comes a segment of kind `ocr_notice`:
  - «نص مستخرج تلقائياً من صورة الصفحة.» for text read by Gemini;
  - «نص مستخرج تلقائياً من صورة الصفحة بقارئ محلي، وقد تكون فيه أخطاء.» for text read by Tesseract;
  - «صفحة ممسوحة لم يُستخرج نصها بعد، وتحتاج OCR.» for a page that was not read.
- Handwritten notes are segments of kind `handwritten`: «ملاحظة بخط اليد: ...».
- The scan image itself is not announced, and it is not counted among the images in the intro.
- Topics in the intro come from the file outline, so headings found by OCR are read on their
  page but are not listed as topics.

**Outro:** «انتهى الملف. الخيارات المتاحة: الاستماع من البداية، الرجوع إلى السلايد السابق،
الذهاب إلى سلايد معيّن، أو الذهاب إلى موضوع معيّن».

**Navigation** (`Navigator`) moves one page or slide at a time:
- `start`, `next`, `previous` and `repeat`;
- `go_to(number or sheet name)` and `go_to_topic(n)`;
- `where_am_i` says «الموضع الحالي: سلايد 4 من 21، ضمن الموضوع الرابع من 15: ...».

Going past either end of the file, or to a number that does not exist, gives a clear sentence.

## Quiz

**Intro:** the title, course, number of questions, time limit, attempts allowed and left, and
the opening and closing times with the time left.

**Each question:**
1. «سؤال 2 من 10».
2. Its type and mark: «اختيار من متعدد، العلامة: 2».
3. The question text.
4. The options: «الخيار أ: ...». True/false questions use «صح» and «خطأ» by default, and a short-answer question says «الإجابة كتابةً».

**Before sending:**
- `confirm` reads the chosen answer: «الإجابة المختارة للسؤال 1: الخيار ب: ... هل يتم إرسال هذه الإجابة؟».
- `confirm_submit` says how many questions have an answer and which do not.

**Time warnings:** at 5 and 1 minutes left (`NARRATOR_QUIZ_WARNINGS`), each said once.

**The correct answer is never read.** `public_quiz` keeps only a whitelist of fields (title,
course, duration, attempts, times, and for each question its type, points, text and option
texts). Everything else is dropped on input, including `correct_answer`, `answer_key`,
`explanation`, `feedback` and `"correct": true` flags. A test feeds such fields in every form
and checks that none of them reaches any segment.

## Assignment, chat, notifications

**Assignment:**
- title and course;
- deadline with time left (or how long ago it passed);
- description;
- attachments: «يحتوي الواجب على مرفقين: ...»;
- status: `not_submitted`, `submitted`, `late` or `graded` (with the mark).

**Chat:**
- One message: sender and role, time, «نص الرسالة: ...», and the attachments.
- Several messages: «عندك 3 رسائل جديدة.», then «الرسالة 1 من 3: ...».
- Roles are said as gender-neutral groups: `instructor` «هيئة التدريس», `teaching_assistant` «فريق التدريس», `student` «الطلبة», `admin` and `support`.

**Notifications** come in six types:

| Type | Fields |
|---|---|
| `lecture_reminder` | course, starts_at, room |
| `room_change` | course, starts_at, old_room, new_room (required) |
| `quiz_reminder` | title, course, closes_at |
| `assignment_due` | title, course, due_at |
| `emergency` | message (required), location, instructions |
| `technical_issue` | message (required), service, expected_fix_at |

Every type also takes `sent_at`. **Emergencies are always read first**, as segments of kind
`emergency` with `priority: "high"`. With several notifications, a summary comes first:
«عندك 6 إشعارات جديدة. تنبيهات الطوارئ أولاً.».

## Configuration

| Variable | Default | |
|---|---|---|
| `CB_EXPLAIN_LANGUAGE` / `NARRATOR_LANGUAGE` | `mixed` | `ar`, `en`, `mixed` |
| `NARRATOR_TIMEZONE` | `Asia/Amman` | times are said in this zone; values without a zone are taken as local |
| `NARRATOR_MAX_TOPICS` | 5 | topics named in the intro |
| `NARRATOR_MAX_TABLE_ROWS` | 10 | rows read per table |
| `NARRATOR_NUMBER_ROWS_FROM` | 4 | tables with this many rows say «الصف 2 من 8» |
| `NARRATOR_WORDS_PER_MINUTE` | 130 | listening-time estimate |
| `NARRATOR_WORDS_PER_IMAGE` | 25 | words counted per useful image in that estimate |
| `NARRATOR_QUIZ_WARNINGS` | `5,1` | quiz warnings, minutes left |
| `NARRATOR_READER_PATH` | `../document-reader/src` | where the document-reader is |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

The tests check the produced text exactly, in Arabic and English. They cover:
- counting, dates and times;
- intro, slides, tables, images, outro and navigation;
- quiz, answer confirmation and time warnings;
- assignment, chat and notifications, with emergencies first;
- the CLI.

The tests use generated files and `examples/`, never `samples-in`. Image descriptions in the
tests come from a fake vision engine, and network access to Gemini is blocked.

## Limitations

- Arabic forms of «you» are avoided. Some phrases use a dual in the genitive or accusative form
  («يحتوي على مرفقين», «باقي ساعتين»), which is what people say.
- Topic ordinals are spoken words up to 20 («الموضوع الخامس عشر»). Beyond 20 they become numbers.
- The listening-time estimate counts words; real speech speed depends on the voice.
- Option letters in Arabic are أ ب ج د هـ ...; how they sound depends on the TTS voice.
