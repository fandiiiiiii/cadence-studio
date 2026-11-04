"""PyInstaller entry point for the packaged Windows build."""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path


def _crash_log() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CadenceStudio" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "crash.log"


def main() -> None:
    try:
        from cadence_studio.__main__ import main as run

        run()
    except BaseException:
        message = traceback.format_exc()
        try:
            _crash_log().write_text(message, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Cadence Studio 启动失败。\n\n{message[-1200:]}\n\n日志：{_crash_log()}",
                    "Cadence Studio",
                    0x10,
                )
            except Exception:  # noqa: BLE001
                pass
        raise


if __name__ == "__main__":
    main()
