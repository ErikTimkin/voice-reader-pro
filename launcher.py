"""Mode selector for Voice Reader Pro.

The existing text-to-speech application is imported unchanged. The live
microphone mode is an independent screen and does not use the Discord bot.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from voice_reader.app import APP_NAME, App
from voice_reader.live_voice_ui import LiveVoiceApp


class ModeLauncher:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_NAME)
        root.geometry("760x560")
        root.minsize(650, 500)
        root.configure(bg="#090d18")
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Launcher.TFrame", background="#090d18")
        style.configure("LauncherTitle.TLabel", background="#090d18", foreground="#edf2ff",
                        font=("Segoe UI", 25, "bold"))
        style.configure("LauncherSub.TLabel", background="#090d18", foreground="#93a0b6",
                        font=("Segoe UI", 10))
        style.configure("LauncherCard.TButton", background="#172238", foreground="#edf2ff",
                        font=("Segoe UI", 15, "bold"), padding=(24, 24), borderwidth=0)
        style.map("LauncherCard.TButton", background=[("active", "#263653")])

        outer = ttk.Frame(root, style="Launcher.TFrame", padding=36)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Voice Reader Pro", style="LauncherTitle.TLabel").pack(pady=(52, 8))
        ttk.Label(outer, text="Выбери режим работы", style="LauncherSub.TLabel").pack(pady=(0, 30))
        self.text_button = ttk.Button(
            outer, text="▤  Текстовая озвучка",
            style="LauncherCard.TButton", command=self.launch_text
        )
        self.text_button.pack(fill="x", padx=35, pady=9)
        self.live_button = ttk.Button(
            outer, text="〰  Изменение голоса в реальном времени",
            style="LauncherCard.TButton", command=self.launch_live
        )
        self.live_button.pack(fill="x", padx=35, pady=9)
        ttk.Label(
            outer,
            text="Текстовая озвучка и голосовые эффекты работают независимо.",
            style="LauncherSub.TLabel"
        ).pack(pady=(22, 0))
        root.protocol("WM_DELETE_WINDOW", root.destroy)

    def _clear(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def show(self):
        self._clear()
        ModeLauncher(self.root)

    def launch_text(self):
        # Run the original text app in its own window. The original app.py,
        # core.py, TTS engines and web UI are not modified by this launcher.
        self.root.withdraw()
        text_window = tk.Toplevel(self.root)
        app = App(text_window)

        def close_text_window():
            app.close()
            if self.root.winfo_exists():
                self.root.deiconify()

        text_window.protocol("WM_DELETE_WINDOW", close_text_window)

    def launch_live(self):
        self._clear()
        LiveVoiceApp(self.root, on_back=self.show)


def run_launcher_smoke_test() -> int:
    root = tk.Tk()
    root.withdraw()
    try:
        launcher = ModeLauncher(root)
        root.update_idletasks()
        if not launcher.text_button.winfo_exists() or not launcher.live_button.winfo_exists():
            raise RuntimeError("Не созданы обе кнопки выбора режима.")
        root.update()
        return 0
    finally:
        root.destroy()


def run_text_ui_smoke_test() -> int:
    root = tk.Tk()
    root.withdraw()
    try:
        app = App(root)
        root.update_idletasks()
        if not hasattr(app, "log") or not app.log.winfo_exists():
            raise RuntimeError("Исходный интерфейс текстовой озвучки не создан.")
        root.update()
        return 0
    finally:
        root.destroy()


def run_live_ui_smoke_test() -> int:
    import numpy as np

    root = tk.Tk()
    root.withdraw()
    app = None
    try:
        app = LiveVoiceApp(root)
        root.update_idletasks()
        if not app.start_button.winfo_exists() or not app.input_combo.winfo_exists():
            raise RuntimeError("Интерфейс голосового режима создан не полностью.")
        sample_rate = 48_000
        samples = np.arange(sample_rate, dtype=np.float32) / sample_rate
        source = (0.15 * np.sin(2 * np.pi * 220 * samples)).astype(np.float32)
        app.engine.configure("Низкий")
        processed = app.engine.process_block(source)
        if processed.shape != source.shape or not np.isfinite(processed).all():
            raise RuntimeError("Встроенный DSP-движок не прошёл smoke test.")
        root.update()
        return 0
    finally:
        if app is not None:
            app.close()
        elif root.winfo_exists():
            root.destroy()


if __name__ == "__main__":
    if "--launcher-smoke-test" in sys.argv:
        raise SystemExit(run_launcher_smoke_test())
    if "--ui-smoke-test" in sys.argv:
        raise SystemExit(run_text_ui_smoke_test())
    if "--live-ui-smoke-test" in sys.argv:
        raise SystemExit(run_live_ui_smoke_test())
    ModeLauncher(tk.Tk()).root.mainloop()
