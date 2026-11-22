"""CLI: python -m narrator [--lang ar|en|mixed] [--now ISO] [--json] <file|quiz|assignment|chat|notifications> ..."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .assignment import AssignmentNarrator
from .chat import ChatNarrator
from .config import NarratorConfig
from .errors import NarratorError
from .files import FileNarrator
from .notifications import NotificationNarrator
from .quiz import QuizNarrator
from .segments import to_dicts


def _load(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise NarratorError(f"cannot read {path}: {exc}") from None
    except ValueError as exc:
        raise NarratorError(f"{path} is not valid JSON: {exc}") from None


def _units(spec: str):
    numbers = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        numbers.update(range(int(a), int(b or a) + 1))
    return numbers


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m narrator", description="CampusBridge narrator (no AI)")
    p.add_argument("--lang", choices=("ar", "en", "mixed"), help="guidance language (default CB_EXPLAIN_LANGUAGE or mixed)")
    p.add_argument("--now", help="current time, ISO (for remaining time; default: now)")
    p.add_argument("--json", action="store_true", help="print segments as JSON")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("file", help="narrate a lecture file (docx, pdf, pptx, xlsx)")
    f.add_argument("path")
    f.add_argument("--meta", help="JSON with course, instructor, uploaded_at, title (from the platform)")
    f.add_argument("--course"), f.add_argument("--instructor"), f.add_argument("--uploaded-at"), f.add_argument("--title")
    f.add_argument("--units", help="only these pages/slides, e.g. 1-3 or 4,21 (intro and outro are kept)")
    f.add_argument("--describe", action="store_true", help="describe images with Gemini (sent to Google)")
    f.add_argument("--ocr", action="store_true",
                   help="read scanned pages and photos (page images are sent to Google; Tesseract fallback)")

    q = sub.add_parser("quiz", help="narrate a quiz JSON")
    q.add_argument("path")
    q.add_argument("--question", type=int, help="only this question (default: intro and all questions)")
    q.add_argument("--confirm", nargs=2, metavar=("QUESTION", "ANSWER"),
                   help="confirmation for an answer: option letter / index, or written text")
    q.add_argument("--warning", type=int, metavar="MINUTES", help="time warning")

    for name, text in (("assignment", "an assignment JSON"), ("chat", "chat messages JSON (object or list)"),
                       ("notifications", "notifications JSON (object or list)")):
        s = sub.add_parser(name, help=f"narrate {text}")
        s.add_argument("path")
    return p


def run(args) -> list:
    config = NarratorConfig.from_env()
    if args.lang:
        config.language = args.lang
    config.validate()
    now = datetime.fromisoformat(args.now) if args.now else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=config.tz())
    if args.command == "file":
        meta = _load(args.meta) if args.meta else {}
        for key in ("course", "instructor", "uploaded_at", "title"):
            if getattr(args, key):
                meta[key] = getattr(args, key)
        wanted = _units(args.units) if args.units else None
        narration = FileNarrator(config).narrate(args.path, meta, now=now, describe=args.describe, units=wanted,
                                                 ocr=args.ocr)
        for w in narration.warnings:
            print(f"warning: {w}", file=sys.stderr)
        if not args.units:
            return narration.segments
        body = [s for number, unit in zip(narration.unit_numbers, narration.units) if number in wanted for s in unit]
        return [narration.intro] + body + [narration.outro]
    if args.command == "quiz":
        quiz = QuizNarrator(_load(args.path), config, now)
        if args.confirm:
            number, answer = args.confirm
            return quiz.confirm(int(number), int(answer) if answer.isdigit() else answer)
        if args.warning:
            return [quiz.time_warning(args.warning)]
        return quiz.question(args.question) if args.question else quiz.all_segments()
    data = _load(args.path)
    if args.command == "assignment":
        return AssignmentNarrator(config, now).narrate(data)
    if args.command == "chat":
        return ChatNarrator(config, now).messages(data if isinstance(data, list) else [data])
    return NotificationNarrator(config, now).notifications(data if isinstance(data, list) else [data])


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        segments = run(args)
    except Exception as exc:                        # narrator and document-reader errors are reported
        if not any(c.__name__ in ("NarratorError", "ReaderError") for c in type(exc).__mro__):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(to_dicts(segments), ensure_ascii=False, indent=2))
    else:
        for s in segments:
            print(f"[{s.kind}] {s.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
