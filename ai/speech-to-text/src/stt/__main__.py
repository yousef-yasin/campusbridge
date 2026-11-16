import argparse
import logging
import sys
from pathlib import Path

from .config import STTConfig
from .errors import STTError
from .live import LiveSession, record_microphone
from .transcriber import Transcriber


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="stt", description="CampusBridge Arabic speech-to-text")
    p.add_argument("--model", help="model size or local path (env STT_MODEL)")
    p.add_argument("--device", help="auto/cpu/cuda (env STT_DEVICE)")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("file", help="transcribe an audio file")
    f.add_argument("audio")
    f.add_argument("-o", "--out", help="output .txt (default: <audio>.txt)")
    m = sub.add_parser("mic", help="live microphone transcription")
    m.add_argument("--seconds", type=float, default=60)
    m.add_argument("--chunk", type=float, default=5.0)
    m.add_argument("-o", "--out", default="transcript.txt")
    s = sub.add_parser("search", help="search a saved transcript (.json) by keyword")
    s.add_argument("transcript")
    s.add_argument("keyword")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg = STTConfig.from_env()
    if args.model:
        cfg.model = args.model
    if args.device:
        cfg.device = args.device
    try:
        if args.cmd == "search":
            from .transcript import Transcript
            hits = Transcript.load(args.transcript).search(args.keyword)
            print(Transcript(hits).to_text() if hits else "No matches.", end="")
            return 0
        tr = Transcriber(cfg)
        if args.cmd == "file":
            t = tr.transcribe_file(args.audio)
            out = t.save(args.out or Path(args.audio).with_suffix(".txt"))
            print(t.to_text(), end="")
        else:
            session = LiveSession(tr, args.out, on_caption=lambda seg: print(seg.text, flush=True))
            tr.model  # fail fast before recording
            record_microphone(session, args.seconds, args.chunk)
            out = Path(args.out)
        print(f"Saved: {out}", file=sys.stderr)
        return 0
    except (STTError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
