"""Camera simulator: python -m camguide <video file | folder of images> [--fps 10] [--out dir] [--ocr]

Prints the command for each moment, saves the auto-captured page (straightened) and, with
--ocr, reads it with document-reader (the page image is sent to Google).
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

from . import CameraGuide, GuideConfig, analyze, read_capture, straighten

IMAGES = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def frames(source: Path, fps: float):
    """(t, frame) from a video (sampled at fps) or the images of a folder (one per 1/fps s)."""
    if source.is_dir():
        for i, path in enumerate(sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGES)):
            frame = cv2.imread(str(path))
            if frame is not None:
                yield i / fps, frame, path.name
        return
    if source.suffix.lower() in IMAGES:
        frame = cv2.imread(str(source))
        if frame is None:
            raise ValueError(f"cannot read image {source}")
        yield 0.0, frame, source.name
        return
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {source}")
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(video_fps / fps))
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            yield index / video_fps, frame, f"frame {index}"
        index += 1
    cap.release()


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m camguide", description="Camera guide simulator (local, OpenCV)")
    p.add_argument("source", help="a video file, an image, or a folder of images")
    p.add_argument("--fps", type=float, default=10.0, help="frames analysed per second (video) / images per second")
    p.add_argument("--out", default="captures", help="folder for the captured page")
    p.add_argument("--ocr", action="store_true", help="read the captured page (document-reader OCR; sent to Google)")
    p.add_argument("--lang", choices=("ar", "en", "mixed"), help="CB_EXPLAIN_LANGUAGE")
    p.add_argument("--all", action="store_true", help="print every frame, not only spoken commands")
    p.add_argument("--json", action="store_true", help="one JSON line per frame")
    p.add_argument("--keep-going", action="store_true", help="single images: report each one (no capture logic)")
    args = p.parse_args(argv)
    source = Path(args.source)
    guide = CameraGuide(GuideConfig.from_env(), args.lang)
    captured = None
    for t, frame, name in frames(source, args.fps):
        if args.keep_going:
            guide.reset()
        advice = guide.feed(frame, t)
        r = advice.report
        if args.json:
            print(json.dumps(dict(advice.to_dict(), name=name), ensure_ascii=False))
        elif args.all or advice.speak or args.keep_going:
            spoken = f"«{advice.speak}»" if advice.speak else "(silent)"
            print(f"{t:6.2f}s  {advice.status:9} {advice.command:11} {spoken:32} {advice.reason}  "
                  f"[{name}, area {r.area:.2f}, cut {','.join(r.cut) or '-'}, {r.ms:.0f} ms]")
        if advice.capture and captured is None:
            captured = (t, frame, r)
            if not args.keep_going:
                break
    if captured is None:
        print("no capture: the checks never passed long enough")
        return 0 if args.keep_going else 1
    t, frame, report = captured
    page = straighten(frame, report.quad)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw_path, page_path = out / "capture-frame.jpg", out / "capture-page.jpg"
    cv2.imwrite(str(raw_path), frame)
    cv2.imwrite(str(page_path), page)
    print(f"captured at {t:.2f}s -> {page_path} ({page.shape[1]}x{page.shape[0]}, straightened); frame: {raw_path}")
    if args.ocr:
        result = read_capture(page, str(page_path), args.lang)
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
        print("OCR:", "ok" if result.ok else f"failed - «{result.message}»")
        if result.ok:
            print(result.speech)
    return 0


if __name__ == "__main__":
    sys.exit(main())
