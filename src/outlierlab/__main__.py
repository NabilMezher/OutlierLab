from __future__ import annotations

import os
import sys
from pathlib import Path


def _configure_windows_tcl() -> None:
    """Point Tkinter to tcl8.6/tk8.6 inside sys.base_prefix when running from a venv on Windows."""
    if sys.platform != "win32":
        return
    tcl_root = Path(sys.base_prefix) / "tcl"
    tcl_dir = tcl_root / "tcl8.6"
    tk_dir = tcl_root / "tk8.6"
    if tcl_dir.is_dir():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
    if tk_dir.is_dir():
        os.environ.setdefault("TK_LIBRARY", str(tk_dir))


_configure_windows_tcl()

from outlierlab.gui.app import main  # noqa: E402

if __name__ == "__main__":
    main()