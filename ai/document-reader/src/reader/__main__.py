import argparse
import json
import logging
import sys

from .config import ReaderConfig
from .document import open_document
from .errors import ReaderError
from .speech import to_speech_text


def _outline_lines(info):
    lines = []
    for e in info.outline:
        where = f"sheet {e.sheet}" if e.sheet else f"{info.unit_type} {e.unit}"
        lines.append(f"{'  ' * (e.level - 1)}- {e.title}  ({where})")
    return lines or ["(no headings or titles found)"]


def _print_info(info):
    print(f"File type: {info.file_type}   {info.unit_type}s: {info.unit_count}   "
          f"images: {info.image_count}   tables: {info.table_count}   language: {info.language}")
    print(f"Title: {info.title}")
    for sheet in info.sheets:
        flags = "".join([" rtl" if sheet.rtl else "", " hidden" if sheet.hidden else ""])
        print(f"Sheet {sheet.index}: {sheet.name} ({sheet.row_count} rows){flags} - "
              f"columns: {', '.join(sheet.columns) or '(none)'}")
    if info.needs_ocr:
        print(f"NEEDS OCR: pages {', '.join(map(str, info.ocr_pages))} have no text layer")
    for w in info.warnings:
        print(f"Warning: {w}")
    print("Outline:")
    for line in _outline_lines(info):
        print(f"  {line}")


def _print_page(page):
    print(f"--- {page.label} ---")
    ocr = page.ocr or {}
    if ocr.get("status") in ("done", "no_text"):
        engine = ocr.get("model") or ocr.get("engine")
        print(f"[OCR: {ocr['status']} by {engine}{', cached' if ocr.get('cached') else ''}, "
              f"{ocr.get('unclear_words', 0)} unclear word(s)]")
    elif page.needs_ocr:
        print("[needs OCR: no text layer]" + (f" ({ocr['reason']})" if ocr.get("reason") else ""))
    for w in page.warnings:
        print(f"[warning] {w}")
    for b in page.blocks:
        tag = f"{b.kind}{b.level or ''}" if b.kind == "heading" else b.kind
        if b.kind == "image":
            img = b.image or {}
            print(f"[image] {img.get('width')}x{img.get('height')} {img.get('path', img.get('sha256', '')[:16])}")
            if img.get("status"):
                status = img["status"] + (f" ({img['category']})" if img.get("category") else "")
                print(f"    status: {status}")
                if img.get("description"):
                    print(f"    short: {img['description']}")
                if img.get("text"):
                    print(f"    text in image: {img['text']}")
                if img.get("unverified_numbers"):
                    print(f"    numbers not in the image: {', '.join(img['unverified_numbers'])}")
                if img.get("reason"):
                    print(f"    reason: {img['reason']}")
        else:
            source = " [ocr]" if b.source == "ocr" else ""
            print(f"[{tag}]{source} [{b.lang or '-'}] {b.text}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="reader", description="CampusBridge document reader (phase 1)")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="extract content from a .docx, .pdf, .pptx, .xlsx or image file")
    e.add_argument("file")
    e.add_argument("--page", help="one page / slide / sheet (number, or sheet name for .xlsx)")
    e.add_argument("--outline", action="store_true", help="only general info and the outline")
    e.add_argument("--json", action="store_true", help="JSON output")
    e.add_argument("--speech", action="store_true", help="text prepared for text-to-speech")
    e.add_argument("--rows", help="xlsx: data rows START:COUNT of the --page sheet (e.g. 1:50)")
    e.add_argument("--images-dir", help="where extracted images are saved (env READER_IMAGES_DIR)")
    e.add_argument("--no-images", action="store_true", help="list images without saving them")
    e.add_argument("--describe", action="store_true",
                   help="describe images with the vision model (sends images to Google)")
    e.add_argument("--explain-lang", choices=("ar", "en", "mixed"),
                   help="language of descriptions (env CB_EXPLAIN_LANGUAGE, default mixed)")
    e.add_argument("--max-images", type=int, help="vision API calls per run (env READER_VISION_MAX_IMAGES)")
    e.add_argument("--detailed", action="store_true", help="--speech: read detailed image descriptions")
    e.add_argument("--references", action="store_true", help="--speech: read references and footnotes too")
    e.add_argument("--ocr", action="store_true",
                   help="read the text of scanned pages and photos (sends page images to Google; "
                        "Tesseract is the local fallback)")
    e.add_argument("--max-ocr-pages", type=int, help="Gemini OCR calls per run (env READER_OCR_MAX_PAGES)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        cfg = ReaderConfig.from_env()
        if args.images_dir:
            cfg.images_dir = args.images_dir
        if args.no_images:
            cfg.extract_images = False
        if args.max_images is not None:
            cfg.vision_max_images = args.max_images
        if args.max_ocr_pages is not None:
            cfg.ocr_max_pages = args.max_ocr_pages
        if args.describe and args.no_images:
            raise ValueError("--describe needs the image files: do not combine it with --no-images")
        with open_document(args.file, cfg) as doc:
            ref = None
            if args.page is not None:
                ref = int(args.page) if args.page.isdigit() else args.page
                if isinstance(ref, str) and doc.file_type != "xlsx":
                    raise ValueError("--page must be a number")
            if args.rows:
                if doc.file_type != "xlsx" or ref is None:
                    raise ValueError("--rows needs an .xlsx file and --page <sheet>")
                start, _, count = args.rows.partition(":")
                rows = list(doc.rows(ref, int(start or 1), int(count or 50)))
                print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else
                      "\n".join(" | ".join(f"{k}: {v}" for k, v in r.items() if v) for r in rows))
                return 0
            if args.outline:
                info = doc.info
                if args.json:
                    print(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
                else:
                    _print_info(info)
                return 0
            pages = [doc.page(ref)] if ref is not None else list(doc.pages())
            if args.ocr:
                from .ocr import PageOCR
                for w in PageOCR(cfg, language=args.explain_lang).read_pages(doc, pages):
                    print(f"Warning: {w}", file=sys.stderr)
            if args.describe:
                from .describe import ImageDescriber
                for w in ImageDescriber(cfg, language=args.explain_lang).describe_pages(pages):
                    print(f"Warning: {w}", file=sys.stderr)
            if args.speech:
                units = to_speech_text(pages, detailed_images=args.detailed, include_references=args.references)
                if args.json:
                    print(json.dumps([u.__dict__ for u in units], ensure_ascii=False, indent=2))
                else:
                    for u in units:
                        print(f"--- {u.unit_type} {u.sheet or u.unit} ---\n{u.text}\n")
                return 0
            if args.json:
                data = {"pages": [pg.to_dict() for pg in pages]}
                if ref is None:
                    data = {"info": doc.info.to_dict(), **data}
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return 0
            if ref is None:
                _print_info(doc.info)
            for page in pages:
                _print_page(page)
        return 0
    except (ReaderError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
