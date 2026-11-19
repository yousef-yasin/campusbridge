"""CLI: python -m questions file <path> [--pages 7,16] | transcript <segments.json>"""
import argparse
import json
import logging
import sys

from . import QuestionConfig, generate_questions, questions_speech
from cb_shared import AIError, from_transcript
from cb_shared.documents import load_units, parse_pages


def build_parser():
    p = argparse.ArgumentParser(prog="python -m questions", description="Practice questions (Gemini; text is sent to Google)")
    p.add_argument("--lang", choices=("ar", "en", "mixed"), help="explanation language (CB_EXPLAIN_LANGUAGE)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--speech", action="store_true", help="text for text-to-speech")
    p.add_argument("--max-calls", type=int, help="AI requests per run (QUESTIONS_MAX_CALLS)")
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("file", help="a lecture file (docx, pdf, pptx, xlsx, image)")
    f.add_argument("path")
    f.add_argument("--pages", help="e.g. 7,16 or 1-3 (default: all)")
    f.add_argument("--ocr", action="store_true", help="read scanned pages and photos (sent to Google)")
    f.add_argument("--describe", action="store_true", help="describe images not described yet (sent to Google)")
    t = sub.add_parser("transcript", help='speech-to-text segments JSON: [{"start", "end", "text"}]')
    t.add_argument("path")
    t.add_argument("--minutes", type=float, default=5.0)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.ERROR)
    args = build_parser().parse_args(argv)
    try:
        cfg = QuestionConfig.from_env()
        if args.max_calls is not None:
            cfg.ai.max_calls = args.max_calls
        if args.command == "file":
            units, _, warnings = load_units(args.path, parse_pages(args.pages), args.ocr, args.describe, args.lang)
        else:
            units, warnings = from_transcript(json.loads(open(args.path, encoding="utf-8").read()), args.minutes * 60), []
        results, more = generate_questions(units, cfg, language=args.lang)
    except (AIError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for w in warnings + more:
        print(f"warning: {w}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    for r in results:
        if args.speech:
            if questions_speech(r):
                print(f"--- {r['label']} ---\n{questions_speech(r)}\n")
            continue
        print(f"=== {r['label']}: {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else ""))
        for q in r.get("questions") or []:
            print(f"  Q: {q['question']}\n  A: {q['answer']}  [{q.get('unit_type')} {q.get('page')}, {q.get('block')}]")
        for problem in r.get("problems") or []:
            print(f"  needs review: {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
