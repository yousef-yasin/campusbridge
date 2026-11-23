"""CLI:
  python -m assistant index <file> --course <name> [--ocr] [--describe]
  python -m assistant ask "<question>" --course <name> [--course <other>] [--conversation <id>]
  python -m assistant courses
"""
import argparse
import json
import logging
import sys

from . import AssistantConfig, Assistant, GeminiEmbedder, Indexer, open_store   # noqa: F401 (sets the path)
from .store import StoreError


def build_parser():
    p = argparse.ArgumentParser(prog="python -m assistant",
                                description="Lecture assistant (RAG; lecture text and questions are sent to Google)")
    p.add_argument("--lang", choices=("ar", "en", "mixed"), help="explanation language (CB_EXPLAIN_LANGUAGE)")
    p.add_argument("--json", action="store_true", help="JSON output")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("index", help="index a lecture file (docx, pdf, pptx, xlsx, image)")
    i.add_argument("path")
    i.add_argument("--course", required=True, help="course id or name")
    i.add_argument("--ocr", action="store_true", help="read scanned pages and photos (sent to Google)")
    i.add_argument("--describe", action="store_true", help="describe images not described yet (sent to Google)")
    a = sub.add_parser("ask", help="ask a question")
    a.add_argument("question")
    a.add_argument("--course", required=True, action="append", help="a course the student may search (repeat)")
    a.add_argument("--conversation", help="conversation id, for follow-up questions")
    a.add_argument("--file", help="limit «اشرح سلايد» / «لخص المحاضرة» to this file")
    a.add_argument("--speech", action="store_true", help="print only the text for text-to-speech")
    a.add_argument("--max-calls", type=int, help="text-model requests (ASSISTANT_MAX_CALLS)")
    sub.add_parser("courses", help="indexed courses and files")
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.ERROR)
    args = build_parser().parse_args(argv)
    cfg = AssistantConfig.from_env()
    try:
        store = open_store(cfg)
        embedder = GeminiEmbedder(cfg.embedding)
        if args.command == "courses":
            courses = store.courses()
            print(json.dumps(courses, ensure_ascii=False, indent=2) if args.json else
                  "\n".join(f"{c}: {', '.join(f)}" for c, f in courses.items()) or "(empty index)")
            return 0
        if args.command == "index":
            indexer = Indexer(store, embedder, cfg)
            report = indexer.index_file(args.path, args.course, args.ocr, args.describe, args.lang)
            for w in indexer.warnings:
                print(f"warning: {w}", file=sys.stderr)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(f"{report['course']} / {report['file']}: {report['units']} units -> {report['chunks']} chunks, "
                      f"{report['embedded']} embedded; split: {report['split_units'] or '-'}; "
                      f"from: {', '.join(report['sources']) or '-'}")
            return 0
        if args.max_calls is not None:
            cfg.ai.max_calls = args.max_calls
        assistant = Assistant(store, embedder, config=cfg, language=args.lang)
        answer = assistant.ask(args.question, args.course, args.conversation, args.file)
    except (StoreError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if type(exc).__name__.endswith("Error") and "reader" in type(exc).__module__:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise
    if args.json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
    elif args.speech:
        print(answer.speech)
    else:
        print(f"[{answer.status}] ({answer.intent}) conversation {answer.conversation}")
        print(answer.answer)
        for s in answer.sources:
            print(f"  source: {s.get('file', 'glossary')} {s.get('unit_type', '')} {s.get('unit', '')}".rstrip())
        for c in answer.chunks:
            print(f"  chunk: {c['file']} {c['unit_type']} {c['unit']} sim={c['similarity']} "
                  f"bm25={c['bm25']} cover={c['coverage']} {'+'.join(c['methods'])}")
        for p in answer.problems:
            print(f"  needs review: {p}")
        for n in answer.notes:
            print(f"  note: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
