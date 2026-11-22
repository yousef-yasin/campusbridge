# Demo audio

Listening samples of the CampusBridge AI modules, for demos and reviews.

**All data in these samples is fake, made up for testing.** That includes the course, the
instructor's name, the dates, the quiz, the assignment and the notification. The only real input
is the CLT lecture file (`CLT_Chapter2_CLT.pptx`), which is lecture material used for testing.

## narrator/

The texts were made by the `ai/narrator` module (fixed templates, no AI). The "current time" was
Wednesday 18 November 2026, 12:00 (Amman), and the explanation language was `mixed`.

| | |
|---|---|
| Engine | Gemini TTS (`ai/text-to-speech`, default engine), no fallback used |
| Voice | Nika |
| Format | MP3, mono, 24 kHz, 64 kbps (converted from the module's WAV output) |

| File | Length | Size | What it contains |
|---|---|---|---|
| `01-file-intro-clt-slide1.mp3` | 42 s | 326 KB | The intro of the CLT lecture file, then slide 1 |
| `02-quiz-question1.mp3` | 30 s | 232 KB | Question 1 of a fake 3-question quiz, with its options |
| `03-assignment.mp3` | 31 s | 244 KB | A fake assignment |
| `04-emergency-notification.mp3` | 21 s | 168 KB | A fake emergency notification |

**`01-file-intro-clt-slide1.mp3`.** The intro gives:
- the course (الإحصاء) and the instructor (د. ليال الزبن);
- the upload date with how long ago;
- the title, the type and the 21 slides;
- the 14 topics, the first five by name;
- the 17 useful images;
- the estimated listening time (about 22 minutes).

Then it reads slide 1, the title slide, which is not counted as a topic:
«سلايد 1 من 21: Chapter 2.» and the subtitle "Central Limit Theorem". The slide's picture (a
person in front of screens) is decorative, so it is skipped.

**`02-quiz-question1.mp3`.** «سؤال 1 من 3.», the type and mark («اختيار من متعدد، العلامة: 2.»),
the question text in English, then «الخيار أ: …» to «الخيار د: …». The correct answer is never read.

**`03-assignment.mp3`.** The title and course, then the deadline with the time left
(«السبت 21 تشرين الثاني الساعة 11 و59 دقيقة مساءً، باقي 3 أيام»). Then the description, the two
attachments (Homework3.pdf, z-table.pdf) and the submission status («لم يُسلَّم بعد»).

**`04-emergency-notification.mp3`.** «تنبيه طوارئ: …»: a fake order to evacuate the science
building, followed by the place, the instructions and the time of the notification.

## Adding files

Only MP3 files under `docs/demo-audio/` are tracked. Every other audio file in the project
(`*.wav`, `*.mp3`, `*.ogg`, ...) is ignored by `.gitignore`. Keep the samples short and the data
fake.
