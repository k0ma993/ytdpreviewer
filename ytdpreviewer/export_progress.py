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


def _build_progress_widgets(
    host: tk.Misc,
    title: str,
    *,
    initial_total: int = 1,
) -> tuple[tk.Label, tk.StringVar, ttk.Progressbar]:
    frame = tk.Frame(host, bg=BG_VIEW, padx=24, pady=20)
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

    style = ttk.Style(host)
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
    return status, percent_var, bar


def run_progress_in_host(
    host: tk.Toplevel,
    parent: tk.Misc,
    title: str,
    worker: Callable[[ExportProgressCallback], T],
    *,
    initial_total: int = 1,
    width: int = 468,
    height: int = 150,
) -> T:
    """Show progress inside an existing *host* window (one-dialog update UX)."""
    for child in host.winfo_children():
        child.destroy()
    host.title(title)
    host.resizable(False, False)
    host.configure(bg=BG_VIEW)
    status, percent_var, bar = _build_progress_widgets(host, title, initial_total=initial_total)

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
            try:
                host.grab_release()
            except tk.TclError:
                pass
            host.destroy()
            return
        host.after(40, pump)

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

    center_tk_window(host, width, height)
    host.attributes("-topmost", True)
    host.grab_set()
    threading.Thread(target=thread_main, name="export-progress", daemon=True).start()
    pump()
    parent.wait_window(host)

    if state["error"] is not None:
        raise state["error"]
    return state["result"]  # type: ignore[return-value]


def run_with_export_progress(
    title: str,
    worker: Callable[[ExportProgressCallback], T],
    *,
    initial_total: int = 1,
    parent: tk.Misc | None = None,
) -> T:
    """
    Run *worker(report)* on a background thread; show a modal progress window.

    *report(current, total, message)* — 1-based *current*, *total* >= 1.

    Pass *parent* when a Tk main loop is already running (e.g. tray background);
    a second ``tk.Tk()`` in the same process can crash Tcl on Windows.
    """
    owns_root = parent is None
    if owns_root:
        host = tk.Tk()
    else:
        host = tk.Toplevel(parent)
        host.transient(parent)

    host.title(title)
    host.configure(bg=BG_VIEW)
    host.resizable(False, False)
    status, percent_var, bar = _build_progress_widgets(host, title, initial_total=initial_total)

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
            if owns_root:
                host.quit()
            else:
                try:
                    host.grab_release()
                except tk.TclError:
                    pass
                host.destroy()
            return
        host.after(40, pump)

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

    center_tk_window(host, 468, 150)
    host.attributes("-topmost", True)
    host.grab_set()
    threading.Thread(target=thread_main, name="export-progress", daemon=True).start()
    pump()
    if owns_root:
        host.mainloop()
        try:
            host.destroy()
        except tk.TclError:
            pass
    elif parent is not None:
        parent.wait_window(host)

    if state["error"] is not None:
        raise state["error"]
    return state["result"]  # type: ignore[return-value]
