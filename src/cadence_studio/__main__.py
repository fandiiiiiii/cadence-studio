"""Double-click launcher: start the local server and open the workbench."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from . import APP_NAME, __version__
from .config import DATA_DIR, ensure_dirs


def ensure_std_streams() -> None:
    """Windowed PyInstaller has no stdout/stderr; uvicorn's logging needs them."""
    if sys.stdout is None:
        stream = (DATA_DIR / "logs" / "stdout.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = stream
    if sys.stderr is None:
        stream = (DATA_DIR / "logs" / "stderr.log").open("a", encoding="utf-8", buffering=1)
        sys.stderr = stream


def find_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError("找不到可用端口（8765–8794）")


def open_when_ready(url: str) -> None:
    import urllib.request

    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "api/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} local workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--gui", action="store_true", help="use the small desktop shell")
    parser.add_argument("--no-gui", action="store_true", help="use the terminal launcher")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    ensure_dirs()
    ensure_std_streams()
    logging.basicConfig(
        filename=str(DATA_DIR / "logs" / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    port = find_port(args.host, args.port)
    use_gui = args.gui or (getattr(sys, "frozen", False) and not args.no_gui)
    if use_gui:
        from .desktop import run_desktop

        run_desktop(args.host, port, open_browser=not args.no_browser)
        return
    url = f"http://{args.host}:{port}/"
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    print()
    print(f"  {APP_NAME}  ·  {__version__}")
    print(f"  {url}")
    print(f"  data: {DATA_DIR}")
    print("  关闭此窗口即可停止工作台。")
    print()
    try:
        from .app import app

        uvicorn.run(app, host=args.host, port=port, log_level="info", access_log=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
