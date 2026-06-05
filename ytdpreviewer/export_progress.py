"""Visible progress window for exports and long-running pack operations."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import TypeVar

import tkinter as tk
from tkinter import ttk

from ytdpreviewer.ui_theme import ACCENT, BG_FIELD, BG_VIEW, FG, FG_DIM, center_tk_window

T = TypeVar("T")

ExportProgressCallback = Callable[[int, int, str], None]


def _clamp_percent(current: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, int(round(100 * current / total))))


def run_with_export_progress(
    title: str,
    worker: Callable[[ExportProgressCallback], T],
    *,
    initial_total: int = 1,
) -> T:
    """
    Run *worker(report)* on a background thread; show a modal progress window.

    *report(current, total, message)* — 1-based *current*, *total* >= 1.
    """
    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG_VIEW)
    root.resizable(False, False)

    frame = tk.Frame(root, bg=BG_VIEW, padx=24, pady=20)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(frame, text=title, bg=BG_VIEW, fg=FG, font=("Segoe UI", 11, "bold")).pack(
        anchor=tk.W
    )
    status = tk.Label(
        frame,
        text="Подготовка…",
        bg=BG_VIEW,
        fg=FG_DIM,
        font=("Segoe UI", 9),
        wraplength=420,
        justify=tk.LEFT,
    )
    status.pack(anchor=tk.W, pady=(10, 6))

    percent_var = tk.StringVar(value="0 %")
    tk.Label(
        frame,
        textvariable=percent_var,
        bg=BG_VIEW,
        fg=ACCENT,
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor=tk.E)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Export.Horizontal.TProgressbar",
        troughcolor=BG_FIELD,
        background=ACCENT,
        bordercolor=BG_FIELD,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        thickness=10,
    )
    bar = ttk.Progressbar(
        frame,
        length=420,
        mode="determinate",
        maximum=max(1, initial_total),
        style="Export.Horizontal.TProgressbar",
    )
    bar.pack(fill=tk.X, pady=(4, 0))

    events: queue.Queue[tuple] = queue.Queue()
    state: dict[str, object] = {"result": None, "error": None, "finished": False}

    def apply_progress(current: int, total: int, message: str) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        bar.configure(maximum=total, value=current)
        percent_var.set(f"{_clamp_percent(current, total)} %")
        status.config(text=message or "…")

    def pump() -> None:
        try:
            while True:
                kind, *payload = events.get_nowait()
                if kind == "progress":
                    apply_progress(*payload)
                elif kind == "done":
                    state["result"] = payload[0]
                elif kind == "error":
                    state["error"] = payload[0]
                elif kind == "finished":
                    state["finished"] = True
                    apply_progress(
                        int(bar.cget("maximum")),
                        int(bar.cget("maximum")),
                        "Готово",
                    )
        except queue.Empty:
            pass
        if state["finished"]:
            root.quit()
            return
        root.after(40, pump)

    def report(current: int, total: int, message: str) -> None:
        events.put(("progress", current, total, message))

    def thread_main() -> None:
        try:
            result = worker(report)
            events.put(("done", result))
        except Exception as exc:
            events.put(("error", exc))
        finally:
            events.put(("finished",))

    center_tk_window(root, 468, 150)
    root.attributes("-topmost", True)
    threading.Thread(target=thread_main, name="export-progress", daemon=True).start()
    pump()
    root.mainloop()
    try:
        root.destroy()
    except tk.TclError:
        pass

    if state["error"] is not None:
        raise state["error"]
    return state["result"]  # type: ignore[return-value]
