"""Small desktop shell for the packaged Windows build.

The browser remains the real UI. This window exists so a packaged .exe can be
double-clicked and stopped without a terminal.
"""

from __future__ import annotations

import threading
import urllib.request
import webbrowser
from typing import Any

import uvicorn

from . import APP_NAME, __version__
from .config import DATA_DIR


def run_desktop(host: str, port: int, *, open_browser: bool = True) -> None:
    import tkinter as tk
    from tkinter import messagebox

    url = f"http://{host}:{port}/"
    # Reuse the same guard as the CLI; windowed builds have no std streams.
    from .__main__ import ensure_std_streams

    ensure_std_streams()
    app = None
    try:
        from .app import app as fastapi_app

        app = fastapi_app
    except Exception as exc:  # pragma: no cover - startup failure
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, f"无法加载工作台：\n{exc}")
        root.destroy()
        return

    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    error: dict[str, Any] = {}

    def serve() -> None:
        try:
            server.run()
        except Exception as exc:  # pragma: no cover
            error["message"] = str(exc)

    thread = threading.Thread(target=serve, name="cadence-desktop-server", daemon=True)
    thread.start()

    root = tk.Tk()
    root.title(f"{APP_NAME} · {__version__}")
    root.geometry("470x255")
    root.minsize(430, 235)
    root.configure(bg="#0d0f10")
    try:
        root.iconbitmap(default="")
    except Exception:  # noqa: BLE001
        pass

    accent = "#c9f56a"
    ink = "#f3f1e8"
    muted = "#8d938b"
    panel = "#15181b"

    tk.Label(root, text="C A D E N C E   /   声 刻", bg="#0d0f10", fg=accent, font=("Segoe UI", 10, "bold")).pack(
        anchor="w", padx=24, pady=(22, 2)
    )
    tk.Label(
        root,
        text="音乐标注工作台",
        bg="#0d0f10",
        fg=ink,
        font=("Segoe UI", 21, "bold"),
    ).pack(anchor="w", padx=24)
    status = tk.StringVar(value="正在启动本地服务…")
    status_label = tk.Label(root, textvariable=status, bg="#0d0f10", fg=muted, font=("Segoe UI", 9))
    status_label.pack(anchor="w", padx=24, pady=(6, 12))

    frame = tk.Frame(root, bg=panel, highlightbackground="#262b2d", highlightthickness=1)
    frame.pack(fill="x", padx=24)
    url_label = tk.Label(frame, text=url, bg=panel, fg=accent, font=("Cascadia Code", 9))
    url_label.pack(anchor="w", padx=12, pady=(10, 1))
    data_label = tk.Label(
        frame,
        text=f"数据目录  {DATA_DIR}",
        bg=panel,
        fg=muted,
        font=("Cascadia Code", 7),
        wraplength=390,
        justify="left",
    )
    data_label.pack(anchor="w", padx=12, pady=(0, 10))

    buttons = tk.Frame(root, bg="#0d0f10")
    buttons.pack(fill="x", padx=24, pady=16)

    def open_workbench() -> None:
        webbrowser.open(url)

    def stop_and_close() -> None:
        server.should_exit = True
        status.set("正在停止…")
        root.after(600, root.destroy)

    open_btn = tk.Button(
        buttons,
        text="打开工作台",
        command=open_workbench,
        bg=accent,
        fg="#101400",
        activebackground="#dcff8d",
        activeforeground="#101400",
        relief="flat",
        bd=0,
        padx=18,
        pady=7,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
        state="disabled",
    )
    open_btn.pack(side="left")
    tk.Button(
        buttons,
        text="停止并退出",
        command=stop_and_close,
        bg="#15181b",
        fg=ink,
        activebackground="#202428",
        activeforeground=ink,
        relief="flat",
        bd=0,
        padx=14,
        pady=7,
        font=("Segoe UI", 9),
        cursor="hand2",
    ).pack(side="left", padx=8)

    def poll() -> None:
        if error:
            status.set("启动失败：请查看 data/logs/app.log")
            status_label.configure(fg="#ff806f")
            return
        try:
            with urllib.request.urlopen(url + "api/health", timeout=1) as response:
                if response.status == 200:
                    status.set("服务已就绪 · 关闭此窗口将停止工作台")
                    open_btn.configure(state="normal")
                    if open_browser:
                        webbrowser.open(url)
                    return
        except Exception:  # noqa: BLE001
            pass
        root.after(400, poll)

    root.protocol("WM_DELETE_WINDOW", stop_and_close)
    root.after(400, poll)
    root.mainloop()
    server.should_exit = True
    thread.join(timeout=3)
