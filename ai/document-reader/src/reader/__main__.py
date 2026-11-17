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
    if page.needs_ocr:
        print("[needs OCR: no text layer]")
    for w in page.warnings:
        print(f"[warning] {w}")
    for b in page.blocks:
        tag = f"{b.kind}{b.level or ''}" if b.kind == "heading" else b.kind
        if b.kind == "image":
            img = b.image or {}
            print(f"[image] {img.get('width')}x{img.get('height')} {img.get('path', img.get('sha256', '')[:16])}")
        else:
            print(f"[{tag}] [{b.lang or '-'}] {b.text}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="reader", description="CampusBridge document reader (phase 1)")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="extract content from a .docx, .pdf, .pptx or .xlsx file")
    e.add_argument("file")
    e.add_argument("--page", help="one page / slide / sheet (number, or sheet name for .xlsx)")
    e.add_argument("--outline", action="store_true", help="only general info and the outline")
    e.add_argument("--json", action="store_true", help="JSON output")
    e.add_argument("--speech", action="store_true", help="text prepared for text-to-speech")
    e.add_argument("--rows", help="xlsx: data rows START:COUNT of the --page sheet (e.g. 1:50)")
    e.add_argument("--images-dir", help="where extracted images are saved (env READER_IMAGES_DIR)")
    e.add_argument("--no-images", action="store_true", help="list images without saving them")
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
            if args.speech:
                units = to_speech_text(pages)
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
