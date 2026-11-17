import argparse
import logging
import sys

from .config import TTSConfig
from .errors import TTSError
from .phrases import PhraseBook
from .synthesizer import Synthesizer
from .voices import PRESET_VOICES


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tts", description="CampusBridge Arabic/English text-to-speech")
    p.add_argument("--engine", help="gemini/edge/piper (env TTS_ENGINE)")
    p.add_argument("--voice", help="voice of the selected engine: preset alias (see 'tts voices'), "
                                   "male, female, or a full voice name")
    p.add_argument("--model", help="Gemini TTS model (env TTS_GEMINI_MODEL)")
    p.add_argument("--style", help="Gemini style instructions (env TTS_GEMINI_STYLE)")
    p.add_argument("--lang", help="auto/ar/en (env TTS_LANGUAGE)")
    p.add_argument("--speed", type=float, help="0.5 to 2.0 (env TTS_SPEED)")
    p.add_argument("--no-cache", action="store_true", help="do not read or write the audio cache")
    p.add_argument("--no-fallback", action="store_true",
                   help="fail instead of falling back to another engine / voice")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("say", help="speak a text")
    s.add_argument("text")
    s.add_argument("-o", "--out", help="output audio file (default: speech.wav / speech.mp3)")
    f = sub.add_parser("file", help="speak a UTF-8 text file")
    f.add_argument("path")
    f.add_argument("-o", "--out", help="output audio file (default: <path> with audio extension)")
    sub.add_parser("voices", help="list the ready-made voices")
    ph = sub.add_parser("phrases", help="quick phrases: list (default), add, edit, remove, say")
    psub = ph.add_subparsers(dest="action")
    psub.add_parser("list", help="list default and custom phrases")
    a = psub.add_parser("add", help="add a custom phrase")
    a.add_argument("text")
    e = psub.add_parser("edit", help="change a custom phrase")
    e.add_argument("id")
    e.add_argument("text")
    r = psub.add_parser("remove", help="delete a custom phrase")
    r.add_argument("id")
    y = psub.add_parser("say", help="speak a phrase by id")
    y.add_argument("id")
    y.add_argument("-o", "--out")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "google_genai"):     # request logs are not useful here
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        cfg = TTSConfig.from_env()
        if args.engine:
            cfg.engine = args.engine
        if args.lang:
            cfg.language = args.lang
        if args.speed is not None:
            cfg.speed = args.speed
        if args.model:
            cfg.gemini_model = args.model
        if args.style is not None:
            cfg.gemini_style = args.style
        if args.voice:
            cfg.set_voice(args.voice)
        if args.no_cache:
            cfg.cache = False
        if args.no_fallback:
            cfg.fallback = False
        cfg.validate()
        if args.cmd == "voices":
            chosen = {"gemini": cfg.gemini_voice, "edge": cfg.edge_voice}
            for v in PRESET_VOICES:
                mark = " (selected)" if v.engine == cfg.engine and v.name == chosen[v.engine] else ""
                kind = f"default {v.gender}" if v.default else v.gender
                print(f"{v.engine}\t{v.alias}\t{v.name}\t{kind}{mark}")
            return 0
        tts = Synthesizer(cfg)
        if args.cmd == "phrases":
            book = PhraseBook(cfg.phrases_file)
            action = args.action or "list"
            if action == "list":
                for ph_ in book.list():
                    print(f"{ph_.id}\t{ph_.text}")
                return 0
            if action == "add":
                print(f"Added: {book.add(args.text).id}", file=sys.stderr)
                return 0
            if action == "edit":
                print(f"Updated: {book.update(args.id, args.text).id}", file=sys.stderr)
                return 0
            if action == "remove":
                book.remove(args.id)
                print(f"Removed: {args.id}", file=sys.stderr)
                return 0
            out = tts.synthesize(book.get(args.id).text, args.out or f"phrase_{args.id}")
        elif args.cmd == "say":
            out = tts.synthesize(args.text, args.out)
        else:
            out = tts.synthesize_file(args.path, args.out)
        if tts.fallbacks:
            print(f"Fallback used: {' -> '.join(tts.fallbacks)} "
                  f"(reason: {tts.fallback_reasons[0]})", file=sys.stderr)
        print(f"Saved: {out}", file=sys.stderr)
        return 0
    except (TTSError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
