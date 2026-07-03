"""Single entry point for PyInstaller builds (launcher GUI or --bot-worker)."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> None:
    if "--bot-worker" in sys.argv:
        from run import main as bot_main
        bot_main()
        return
    from tools.bootstrap_win import ensure_launcher_prerequisites
    ensure_launcher_prerequisites()
    from tools.launcher import main as launcher_main
    launcher_main()


if __name__ == "__main__":
    main()
