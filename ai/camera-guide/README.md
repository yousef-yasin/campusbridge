# Camera guide (CampusBridge AI, STB-16 to STB-23)

Spoken guidance that helps a blind or visually impaired student photograph a page. It runs
**locally with OpenCV: no AI and no internet** for the guidance. The app sends each camera frame
and plays one short command («يمين», «قرّب», «اثبت» …). When the page is well framed for long
enough, the photo is taken. The page is then straightened and read with document-reader's OCR,
ready for the narrator and text-to-speech.

## How the web team uses it

```python
from camguide import CameraGuide, read_capture, scale_quad, straighten

guide = CameraGuide()                       # language: CB_EXPLAIN_LANGUAGE (ai/shared)
for frame, t in camera_preview():           # e.g. 10 frames per second from the live preview
    advice = guide.feed(frame, t)           # t in seconds
    if advice.speak:                        # None while the command must not be repeated
        play(advice.command)                # pre-recorded voice (see "Command voices")
    show_on_screen(advice.text, advice.reason)
    if advice.capture:
        photo = take_full_resolution_photo()            # NOT the preview frame (see below)
        quad = scale_quad(advice.report.quad, advice.report.size, (photo.shape[1], photo.shape[0]))
        result = read_capture(straighten(photo, quad))
        say(result.speech if result.ok else result.message)
        break
```

`Advice` holds:
- `status`: `searching`, `adjusting`, `ready` or `captured`;
- `command`: a key, for example `move_right`;
- `text` (the command in the student's language), `reason`, and `speak` (the text to say now, or
  `None`);
- `capture` (True once), `failed` (every failing check, in priority order), and `report` (the
  measurements).

`advice.to_dict()` gives JSON for a web API. A server can receive frames (for example as JPEG
over a WebSocket at 5 to 10 per second, scaled to about 720 px wide) and send each `Advice`
back. The same code also runs on the device in a Python runtime.

**Auto-capture must take a FULL-RESOLUTION photo from the camera.** The preview frames used
for guiding are small and compressed: fine for finding the page, too poor for reading
handwriting. On `capture`, the app asks the camera for a real photo (`ImageCapture.takePhoto()`
on the web, the native capture API on a phone). It then moves the page corners from the
preview frame to the photo with `scale_quad`, straightens the page, and sends it to OCR. Both
must keep the same aspect ratio; if they don't, the corners have to be mapped with the camera's
crop.

## Checks and commands

Each frame is scaled to 480 px wide before the checks.

| Check | Measure | Command (ar / en) |
|---|---|---|
| Page found | writing on a light background (see "How the page is found") | «وجّه الكاميرا نحو الورقة» / "Point the camera at the page" |
| Light | mean grey level < 70 | «الإضاءة ضعيفة» / "The light is too low" |
| Page cut | writing runs off a side for more than 12% of it | «بعّد» / "Move back"; one side only, page not too big: move towards it |
| Position | page centre more than 12% from the frame centre | «يمين» «يسار» «ارفع» «نزّل» / "Right" "Left" "Up" "Down" |
| Distance | writing covers less than 50% of the frame | «قرّب» / "Move closer" |
| Tilt | page turned more than 12°, or paper sides with a ratio under 0.78 (phone not level) | «الموبايل مائل، خلّيه موازي للورقة» |
| Glare | more than 6% of the page saturated | «في انعكاس قوي، حرّك الموبايل قليلاً» |
| Sharpness | variance of the Laplacian on the page < 60 | «اثبت» / "Hold still" |
| All pass | | «ممتاز، اثبت», then after 1 s «تم التصوير» |
| OCR found no text (STB-23) | | «ما قدرت أقرأ الورقة، جرّب تصوّر مرة ثانية» |

- **Directions are moves of the phone, not of the page.** A page on the right of the frame means
  the phone moves right. For a front camera preview (mirrored), set `mirrored=True`
  (`CAMERA_MIRRORED=1`).
- **Fixed priority, one command at a time:** page found, light, cut, position, distance, tilt,
  glare, sharpness. Light comes first because nothing else can be judged in the dark. Sharpness
  comes last because it is only worth fixing once the page is framed.
- **No flooding:**
  - a new command must be seen on 2 frames in a row;
  - there are at least 0.8 s between two spoken commands;
  - the same command is not repeated within 3 s (`CAMERA_REPEAT_SECONDS`).
- **Auto-capture** happens when every check passes for `CAMERA_HOLD_SECONDS` (default 1.0 s), and
  then `capture` is True once. `reset()` starts again.
- **Language:** the shared `CB_EXPLAIN_LANGUAGE` from `ai/shared`. `ar` and `mixed` give Arabic
  commands, and `en` gives English.

## How the page is found

White paper on a light table has weak edges, so the page is found from its **writing**:
1. An adaptive threshold finds dark strokes. They are kept only where the background (the grey
   level with the writing closed over) is at least half as bright as the brightest area, so
   shadowed paper counts and a dark table does not.
2. The strokes are joined into blocks. The biggest block, plus the blocks of similar size, is
   the content.
3. Its rotated box, after dropping the outermost 0.2% of the writing, is the page area.

If the paper's own edges are clear, its four corners are used instead, and they also show a
tilted phone (perspective). "Cut" is measured on the frame border: real cut-off writing covers
much of a side, while scattered marks (the pages underneath, a pen) do not.

**Speed:** about 20 ms per frame on a laptop CPU for 720 to 1080 px frames (the median over the
test video). The first frame of a new process takes 40 to 55 ms. The test requires under 50 ms.

## After the capture

- **`straighten(photo, quad)`** corrects the perspective, so the page becomes an upright rectangle
  with a small margin.
- **`read_capture(page)`** saves it as JPEG and reads it with document-reader as an image file,
  using the phase 4 OCR path. The page image is sent to Google; without internet, Tesseract is
  the fallback.
  - `ReadResult.speech` is ready for the narrator and text-to-speech.
  - If no text comes out, `message` is «ما قدرت أقرأ الورقة، جرّب تصوّر مرة ثانية».
- **Handwritten pages** (document-reader):
  - Speech says once «الورقة مكتوبة بخط اليد.», then reads the text normally.
  - Without internet, Tesseract cannot read handwriting. The student hears «الورقة مكتوبة بخط اليد
    على الأغلب، ولا يمكن قراءتها بدون إنترنت. جرّب مرة أخرى عند توفر الاتصال.» instead of wrong
    text.

## Camera simulator (CLI)

```bash
# from ai/camera-guide, with PYTHONPATH=src
python -m camguide ../samples-in/IMG_7113.MOV --fps 10              # spoken commands over time
python -m camguide ../samples-in/IMG_7113.MOV --fps 10 --ocr        # + read the captured page (Google)
python -m camguide frames/ --fps 10 --all                           # a folder of images, every frame
python -m camguide photo.jpg --keep-going                           # status and command of one image
python -m camguide video.mp4 --json                                 # one JSON line per frame
```

It prints the time, status, command, spoken text and reason. It saves `capture-frame.jpg` and
the straightened `capture-page.jpg` in `--out` (default `captures/`, git-ignored).

## Command voices

The commands repeat all the time, so each one is synthesised **once** with the text-to-speech
module (Gemini, voice Nika) and kept:

```bash
# from ai/camera-guide, with the text-to-speech venv (no OpenCV needed)
../text-to-speech/.venv/Scripts/python src/camguide/voices.py --lang ar   # -> voices/ar/<command>.wav + index.json
```

- **No voice mixing:** a command that cannot be made with Nika (for example on a 429 quota error)
  is left missing instead of being recorded with another voice. The old clip is removed, and
  `index.json` lists it with the error. Run again later; clips already made come from the
  text-to-speech cache at no cost. `--allow-fallback` accepts another voice.
- `voices/` is git-ignored.

## Settings

Each setting is a `CAMERA_*` variable, upper case.

| Setting | Default | Meaning |
|---|---|---|
| `WORK_WIDTH` | 480 | analysis width |
| `MIN_AREA` | 0.50 | writing smaller than this share of the frame → «قرّب» |
| `CENTER_TOLERANCE` | 0.12 | allowed offset of the page centre |
| `EDGE_MARGIN` / `CUT_SHARE` | 0.015 / 0.12 | border strip checked / covered share that means "cut" |
| `MAX_ROTATION` / `MIN_SIDE_RATIO` | 12° / 0.78 | tilt limits |
| `MIN_SHARPNESS` | 60 | blur limit |
| `MIN_BRIGHTNESS` | 70 | darkness limit |
| `MAX_GLARE` | 0.06 | glare limit |
| `HOLD_SECONDS` | 1.0 | checks must pass this long before the photo |
| `REPEAT_SECONDS` / `MIN_GAP_SECONDS` | 3.0 / 0.8 | no-repeat rules |
| `STABLE_FRAMES` | 2 | frames a new command must last |
| `MIRRORED` | 0 | front camera preview |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

The tests draw their own frames: a page in the centre, right, left, high, low, small, cut,
turned, a tilted phone, shaky, dark, with glare, and no page. They also cover priority, no
repeats, auto-capture after 1 s and no capture after a short good moment, speed, straightening,
the STB-23 message with a fake OCR engine, the CLI, and the command voices.

## Limitations

- The page is found from its writing: a blank page is "not found".
- On white paper on a white table the paper's edges are often not found. The tilt of the phone
  (perspective) is then not measured; only the page's turn in the frame is.
- The thresholds were tuned on our test video and photos. Real devices may need different
  values (all are settings).
