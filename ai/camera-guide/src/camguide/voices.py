"""Pre-recorded command voices: every fixed command is synthesised ONCE (text-to-speech module,
default Gemini voice Nika) and kept, because the guide repeats them all the time.

python src/camguide/voices.py [--lang ar|en] [--out DIR]   (with the text-to-speech venv)
-> DIR/<lang>/<command>.wav (or .mp3 after a fallback) and DIR/<lang>/index.json
The text-to-speech module also caches each clip (.tts-cache), so a second run costs nothing.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from .commands import COMMANDS
except ImportError:              # run as a script from the text-to-speech venv (no OpenCV needed)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from commands import COMMANDS

_ROOT = Path(__file__).resolve().parents[2]          # ai/camera-guide
DEFAULT_DIR = _ROOT / "voices"


def build(lang: str = "ar", out_dir=DEFAULT_DIR, synthesizer=None, strict: bool = True) -> dict:
    """Synthesise every command; returns {command: {"text", "file" or None, "error"}}.

    strict (default): no voice fallback. The commands must all sound the same, so a command
    that cannot be made with the main voice (e.g. Gemini's daily quota is used up) is left
    missing - run again later; the clips already made come from the cache at no cost.
    """
    if synthesizer is None:
        tts_src = _ROOT.parent / "text-to-speech" / "src"
        if str(tts_src) not in sys.path:
            sys.path.insert(0, str(tts_src))
        from tts import Synthesizer, TTSConfig
        cfg = TTSConfig.from_env()
        if strict:
            cfg.fallback = False
        synthesizer = Synthesizer(cfg)
    folder = Path(out_dir) / lang
    folder.mkdir(parents=True, exist_ok=True)
    index = {}
    for key, (ar, en) in COMMANDS.items():
        text = en if lang == "en" else ar
        try:
            path = synthesizer.synthesize(text, folder / key)
        except Exception as exc:                       # TTSError: quota, offline...
            for old in folder.glob(f"{key}.*"):         # never keep a clip in another voice
                old.unlink()
            index[key] = {"text": text, "file": None, "error": str(exc)[:160]}
            continue
        for old in folder.glob(f"{key}.*"):
            if old != path:
                old.unlink()
        index[key] = {"text": text, "file": path.name, "error": None}
    (folder / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="voices.py")
    p.add_argument("--lang", choices=("ar", "en"), default="ar")
    p.add_argument("--out", default=str(DEFAULT_DIR))
    p.add_argument("--allow-fallback", action="store_true", help="accept another voice when the main one fails")
    args = p.parse_args(argv)
    index = build(args.lang, args.out, strict=not args.allow_fallback)
    for key, item in index.items():
        status = item["file"] or f"MISSING ({item['error'][:70]})"
        print(f"{key:12} {status:20} «{item['text']}»")
    missing = [k for k, v in index.items() if not v["file"]]
    print(f"{len(index) - len(missing)} of {len(index)} commands ready" + (f"; run again later for: {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
