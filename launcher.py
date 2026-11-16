"""Independent mode selector. Each bot runs in its own OS process."""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

APP_NAME = "Voice Reader Pro"
BG, PANEL, TEXT, MUTED, ACCENT = "#090d18", "#121a2b", "#edf2ff", "#93a0b6", "#887cff"


def _child_command(mode: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, f"--mode-{mode}"]
    return [sys.executable, str(Path(__file__).resolve()), f"--mode-{mode}"]


def _run_mode(mode: str) -> int:
    if mode == "text":
        from voice_reader.app import App
        root = tk.Tk()
        App(root)
        root.mainloop()
        return 0
    if mode == "live":
        from voice_reader.live_app import run
        return run()
    raise ValueError(f"Unknown mode: {mode}")


class ModeSelector:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.child = None
        root.title(APP_NAME)
        root.geometry("700x520")
        root.minsize(620, 460)
        root.configure(bg=BG)
        root.option_add("*Font", ("Segoe UI", 10))
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Shell.TFrame", background=BG)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 26, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Card.TFrame", background=PANEL)
        style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 15, "bold"))
        style.configure("CardSub.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Mode.TButton", background=ACCENT, foreground="white",
                        font=("Segoe UI", 12, "bold"), padding=(18, 14), borderwidth=0)
        style.map("Mode.TButton", background=[("active", "#9a90ff"), ("disabled", "#4c4a70")])
        style.configure("Status.TLabel", background=BG, foreground="#a6f0d2", font=("Segoe UI", 9))

        outer = ttk.Frame(root, style="Shell.TFrame", padding=28)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Voice Reader Pro", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Выбери, какой режим запустить", style="Sub.TLabel").pack(anchor="w", pady=(5, 22))

        self.status = tk.StringVar(value="Оба режима изолированы друг от друга")
        for title, desc, mode, button_text in (
            ("Текстовый бот", "Озвучивает сообщения, отправленные через веб-страницу, в голосовом канале Discord.\nСтабильная версия №348.", "text", "▶  Запустить текстовый бот"),
            ("Изменение голоса", "Обрабатывает звук с микрофона в реальном времени.\nЭффекты микрофона, ручная настройка и вывод обработанного звука в Discord через VB-CABLE.", "live", "▶  Запустить изменение голоса"),
        ):
            card = ttk.Frame(outer, style="Card.TFrame", padding=20)
            card.pack(fill="x", pady=8)
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=desc, style="CardSub.TLabel", justify="left").pack(anchor="w", pady=(7, 15))
            ttk.Button(card, text=button_text, style="Mode.TButton",
                       command=lambda m=mode: self.launch(m)).pack(fill="x")
        ttk.Label(outer, textvariable=self.status, style="Status.TLabel").pack(anchor="w", pady=(14, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._poll()

    def launch(self, mode: str):
        if self.child is not None and self.child.poll() is None:
            messagebox.showwarning(APP_NAME, "Сначала закрой уже запущенный режим.")
            return
        try:
            self.child = subprocess.Popen(_child_command(mode), cwd=str(Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent))
            self.status.set("Запущен: " + ("текстовый бот" if mode == "text" else "изменение голоса"))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Не удалось запустить режим: {exc}")

    def _poll(self):
        if self.child is not None and self.child.poll() is not None:
            self.status.set("Режим закрыт. Можно выбрать другой.")
            self.child = None
        self.root.after(500, self._poll)

    def close(self):
        if self.child is not None and self.child.poll() is None:
            try:
                self.child.terminate()
            except Exception:
                pass
        self.root.destroy()


def run_live_ui_smoke_test() -> int:
    """Exercise the packaged live UI and DSP without requiring a physical mic."""
    import numpy as np
    from voice_reader.live_voice_ui import LiveVoiceApp

    root = tk.Tk()
    root.withdraw()
    app = None
    try:
        app = LiveVoiceApp(root)
        root.update_idletasks()
        if not app.start_button.winfo_exists() or not app.input_combo.winfo_exists():
            raise RuntimeError("Live voice UI was not created completely")
        sample_rate = 48_000
        samples = np.arange(sample_rate, dtype=np.float32) / sample_rate
        source = (0.15 * np.sin(2.0 * np.pi * 220.0 * samples)).astype(np.float32)
        app.engine.configure("Низкий")
        processed = app.engine.process_block(source)
        if processed.shape != source.shape or not np.isfinite(processed).all():
            raise RuntimeError("Live DSP failed in the packaged UI smoke test")
        if float(np.sqrt(np.mean(np.square(processed)))) < 0.001:
            raise RuntimeError("Live DSP returned silent audio in the packaged UI smoke test")
        root.update()
        return 0
    finally:
        if app is not None:
            app.close()
        elif root.winfo_exists():
            root.destroy()


def main() -> int:
    if len(sys.argv) > 1:
        if sys.argv[1] == "--voice-smoke-test" and len(sys.argv) >= 3:
            from voice_reader.app import run_frozen_voice_smoke_test
            return run_frozen_voice_smoke_test(sys.argv[2])
        if sys.argv[1] == "--ui-smoke-test":
            from voice_reader.app import run_frozen_ui_smoke_test
            return run_frozen_ui_smoke_test()
        if sys.argv[1] == "--live-ui-smoke-test":
            return run_live_ui_smoke_test()
        if sys.argv[1] == "--launcher-smoke-test":
            root = tk.Tk()
            root.withdraw()
            ModeSelector(root)
            root.update_idletasks()
            root.destroy()
            return 0
        if sys.argv[1] == "--mode-text":
            return _run_mode("text")
        if sys.argv[1] == "--mode-live":
            return _run_mode("live")
    root = tk.Tk()
    ModeSelector(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
