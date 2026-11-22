"""CLI: python -m summarizer file <path> [--pages 7,16] | transcript <segments.json>"""
import argparse
import json
import logging
import sys

from . import SummaryConfig, file_summary_speech, summarize_units, summary_speech  # noqa: F401 (sets the path)
from cb_shared import AIError, from_transcript
from cb_shared.documents import load_units, parse_pages


def build_parser():
    p = argparse.ArgumentParser(prog="python -m summarizer", description="Page summaries (Gemini; text is sent to Google)")
    p.add_argument("--lang", choices=("ar", "en", "mixed"), help="explanation language (CB_EXPLAIN_LANGUAGE)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--speech", action="store_true", help="text for text-to-speech")
    p.add_argument("--max-calls", type=int, help="AI requests per run (SUMMARY_MAX_CALLS)")
    p.add_argument("--no-file-summary", action="store_true", help="only page summaries")
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("file", help="a lecture file (docx, pdf, pptx, xlsx, image)")
    f.add_argument("path")
    f.add_argument("--pages", help="e.g. 7,16 or 1-3 (default: all)")
    f.add_argument("--ocr", action="store_true", help="read scanned pages and photos (sent to Google)")
    f.add_argument("--describe", action="store_true", help="describe images not described yet (sent to Google)")
    t = sub.add_parser("transcript", help='speech-to-text segments JSON: [{"start", "end", "text"}]')
    t.add_argument("path")
    t.add_argument("--minutes", type=float, default=5.0, help="minutes per part")
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.ERROR)
    args = build_parser().parse_args(argv)
    try:
        cfg = SummaryConfig.from_env()
        if args.max_calls is not None:
            cfg.ai.max_calls = args.max_calls
        if args.command == "file":
            units, title, warnings = load_units(args.path, parse_pages(args.pages), args.ocr, args.describe, args.lang)
        else:
            segments = json.loads(open(args.path, encoding="utf-8").read())
            units, title, warnings = from_transcript(segments, args.minutes * 60), "", []
        results, whole, more = summarize_units(units, cfg, language=args.lang, title=title,
                                               file_summary=not args.no_file_summary)
    except (AIError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if type(exc).__name__.endswith("Error") and "reader" in type(exc).__module__:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise
    for w in warnings + more:
        print(f"warning: {w}", file=sys.stderr)
    if args.json:
        print(json.dumps({"pages": results, "file": whole}, ensure_ascii=False, indent=2))
    elif args.speech:
        for r in results:
            text = summary_speech(r)
            if text:
                print(f"--- {r['label']} ---\n{text}\n")
        if file_summary_speech(whole):
            print(f"--- file ---\n{file_summary_speech(whole)}")
    else:
        for r in results:
            print(f"=== {r['label']}: {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else ""))
            if r.get("summary"):
                print(f"summary: {r['summary']}")
                for p in r.get("points") or []:
                    print(f"  - [{p.get('block')}] {p.get('text')}")
                for t in r.get("terms") or []:
                    print(f"  term: {t.get('term')} = {t.get('meaning')}")
            for problem in r.get("problems") or []:
                print(f"  needs review: {problem}")
        if whole:
            print(f"=== file: {whole['status']}" + (f"\n{whole['summary']}" if whole.get("summary") else
                                                     f" ({whole.get('reason')})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
