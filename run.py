"""Entry point.  Run:  python run.py

Make sure the Roblox game window is open and you are standing next to the shop vendor,
then start the bot. It watches for the "Shop has been restocked!" banner and buys the
items you selected in config.json (buy.items).
"""
import os
import sys
import traceback
from datetime import datetime

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import appconfig


def _attach_stderr_log(root: str) -> None:
    """Capture uncaught tracebacks — the launcher runs the bot with stdout/stderr hidden."""
    try:
        logdir = os.path.join(root, "logs")
        os.makedirs(logdir, exist_ok=True)
        path = os.path.join(logdir, datetime.now().strftime("bot_%Y%m%d_%H%M%S") + "_stderr.log")
        fh = open(path, "a", encoding="utf-8", buffering=1)

        class _Tee:
            def __init__(self, stream):
                self._stream = stream

            def write(self, data):
                try:
                    fh.write(data)
                except Exception:
                    pass
                if self._stream is not None:
                    try:
                        self._stream.write(data)
                    except Exception:
                        pass

            def flush(self):
                try:
                    fh.flush()
                except Exception:
                    pass
                if self._stream is not None:
                    try:
                        self._stream.flush()
                    except Exception:
                        pass

        sys.stderr = _Tee(getattr(sys, "__stderr__", None))
    except Exception:
        pass


def main():
    root = appconfig.ROOT
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    _attach_stderr_log(root)
    try:
        from src.watcher import Watcher
        Watcher().run()
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
