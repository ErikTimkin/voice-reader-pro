"""Tkinter UI for the separate live microphone mode."""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from voice_reader.live_audio import LiveVoiceEngine, PRESETS, list_audio_devices


class LiveVoiceApp:
    def __init__(self, root: tk.Tk, on_back=None):
        self.root = root
        self.on_back = on_back
        self.engine = LiveVoiceEngine()
        self.devices = []
        self.input_lookup = {}
        self.output_lookup = {}
        self._poll_job = None
        self.ai_process = None

        root.title("Voice Reader Pro — Изменение голоса")
        root.geometry("760x720")
        root.minsize(650, 620)
        root.configure(bg="#090d18")
        root.option_add("*Font", ("Segoe UI", 9))

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg, panel, field = "#090d18", "#121a2b", "#0b1322"
        text, muted, purple, border = "#edf2ff", "#93a0b6", "#887cff", "#26334b"
        style.configure("Live.TFrame", background=bg)
        style.configure("LiveCard.TFrame", background=panel)
        style.configure("LiveTitle.TLabel", background=bg, foreground=text, font=("Segoe UI", 22, "bold"))
        style.configure("LiveSub.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("LiveCardTitle.TLabel", background=panel, foreground=text, font=("Segoe UI", 12, "bold"))
        style.configure("LiveField.TLabel", background=panel, foreground="#aebbd0", font=("Segoe UI", 9, "bold"))
        style.configure("LiveStatus.TLabel", background=bg, foreground="#a6f0d2", font=("Segoe UI", 10, "bold"))
        style.configure("Live.TCombobox", fieldbackground=field, background=field, foreground=text, padding=7)
        style.configure("Live.TButton", background="#26334b", foreground=text, padding=(12, 9), borderwidth=0)
        style.map("Live.TButton", background=[("active", "#33435f")])
        style.configure("LivePrimary.TButton", background=purple, foreground="white",
                        font=("Segoe UI", 11, "bold"), padding=(16, 13), borderwidth=0)
        style.map("LivePrimary.TButton", background=[("active", "#9a90ff"), ("disabled", "#4c4a70")])

        outer = ttk.Frame(root, style="Live.TFrame", padding=22)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="Live.TFrame")
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="Изменение голоса", style="LiveTitle.TLabel").pack(anchor="w")
        ttk.Label(header, text="Эффекты микрофона и AI-преобразование в реальном времени", style="LiveSub.TLabel").pack(anchor="w", pady=(3, 0))
        if on_back:
            ttk.Button(header, text="← Все режимы", style="Live.TButton", command=self.back).pack(anchor="e", pady=(8, 0))

        devices_card = ttk.Frame(outer, style="LiveCard.TFrame", padding=15)
        devices_card.pack(fill="x", pady=(0, 12))
        ttk.Label(devices_card, text="Аудиоустройства", style="LiveCardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.input_combo = ttk.Combobox(devices_card, textvariable=self.input_var, state="readonly")
        self.output_combo = ttk.Combobox(devices_card, textvariable=self.output_var, state="readonly")
        ttk.Label(devices_card, text="МИКРОФОН (ВХОД)", style="LiveField.TLabel").pack(anchor="w")
        self.input_combo.pack(fill="x", pady=(4, 10))
        ttk.Label(devices_card, text="ВИРТУАЛЬНЫЙ КАБЕЛЬ (ВЫХОД)", style="LiveField.TLabel").pack(anchor="w")
        self.output_combo.pack(fill="x", pady=(4, 8))
        device_actions = ttk.Frame(devices_card, style="LiveCard.TFrame")
        device_actions.pack(fill="x")
        ttk.Button(device_actions, text="Обновить устройства", style="Live.TButton", command=self.refresh_devices).pack(side="left")
        ttk.Button(device_actions, text="Установить VB-CABLE", style="Live.TButton",
                   command=lambda: webbrowser.open("https://vb-audio.com/Cable/")).pack(side="right")
        ttk.Button(device_actions, text="AI-преобразование (RVC)", style="Live.TButton",
                   command=self.launch_ai_voice).pack(side="right", padx=(0, 8))
        ttk.Label(devices_card,
                  text="В Discord выбери CABLE Output как устройство ввода. Здесь выбирается CABLE Input.",
                  style="LiveSub.TLabel", wraplength=650).pack(anchor="w", pady=(9, 0))

        presets_card = ttk.Frame(outer, style="LiveCard.TFrame", padding=15)
        presets_card.pack(fill="x", pady=(0, 12))
        ttk.Label(presets_card, text="Готовые эффекты", style="LiveCardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        presets_grid = ttk.Frame(presets_card, style="LiveCard.TFrame")
        presets_grid.pack(fill="x")
        for i, name in enumerate(PRESETS):
            button = ttk.Button(presets_grid, text=name, style="Live.TButton",
                                command=lambda selected=name: self.select_preset(selected))
            button.grid(row=i // 3, column=i % 3, sticky="ew", padx=4, pady=4)
            presets_grid.columnconfigure(i % 3, weight=1)
        self.selected_preset = tk.StringVar(value="Выбран эффект: Обычный")
        ttk.Label(presets_card, textvariable=self.selected_preset, style="LiveSub.TLabel").pack(anchor="w", pady=(7, 0))

        custom_card = ttk.Frame(outer, style="LiveCard.TFrame", padding=15)
        custom_card.pack(fill="x", pady=(0, 12))
        ttk.Label(custom_card, text="Ручная настройка", style="LiveCardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        self.values = {
            "pitch": tk.DoubleVar(value=0.0),
            "bass": tk.DoubleVar(value=0.0),
            "treble": tk.DoubleVar(value=0.0),
            "drive": tk.DoubleVar(value=0.0),
        }
        self.value_labels = {}
        slider_specs = (
            ("pitch", "Высота голоса", -8, 8, " полутонов"),
            ("bass", "Бас", -12, 12, " дБ"),
            ("treble", "Высокие частоты", -12, 12, " дБ"),
            ("drive", "Искажение", 0, 30, " дБ"),
        )
        for key, title, minimum, maximum, suffix in slider_specs:
            line = ttk.Frame(custom_card, style="LiveCard.TFrame")
            line.pack(fill="x", pady=3)
            ttk.Label(line, text=title, style="LiveField.TLabel").pack(side="left")
            value_label = ttk.Label(line, text=f"0{suffix}", style="LiveSub.TLabel")
            value_label.pack(side="right")
            self.value_labels[key] = (value_label, suffix)
            scale = ttk.Scale(custom_card, from_=minimum, to=maximum, variable=self.values[key],
                              command=lambda value, k=key: self._slider_changed(k, value))
            scale.pack(fill="x", pady=(0, 4))

        control = ttk.Frame(outer, style="Live.TFrame")
        control.pack(fill="x", pady=(2, 0))
        self.status = tk.StringVar(value="Остановлено")
        ttk.Label(control, textvariable=self.status, style="LiveStatus.TLabel").pack(anchor="w", pady=(0, 8))
        self.start_button = ttk.Button(control, text="▶  Включить голосовой эффект",
                                        style="LivePrimary.TButton", command=self.toggle)
        self.start_button.pack(fill="x")
        ttk.Label(outer,
                  text="Для работы нужен установленный виртуальный аудиокабель. Установка драйвера выполняется отдельно с сайта VB-Audio.",
                  style="LiveSub.TLabel", wraplength=690).pack(anchor="w", pady=(10, 0))

        self.refresh_devices()
        self.engine.configure("Обычный")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._schedule_poll()

    def launch_ai_voice(self):
        """Launch the optional neural RVC converter as an independent process."""
        if self.ai_process is not None and self.ai_process.poll() is None:
            messagebox.showinfo("Voice Reader Pro", "AI-преобразование уже запущено.")
            return
        if self.engine.running:
            self.stop()
        data_dir = Path(os.getenv("APPDATA", Path.home())) / "VoiceReaderPro"
        config_path = data_dir / "ai_rvc_exe.txt"
        executable = None
        try:
            saved = config_path.read_text(encoding="utf-8").strip()
            if saved and Path(saved).is_file():
                executable = Path(saved)
        except OSError:
            pass
        if executable is None:
            messagebox.showinfo(
                "AI-преобразование голоса",
                "Это отдельный локальный RVC-движок. Скачай Windows GUI + CLI пакет "
                "vc-rs со страницы релизов, распакуй его целиком и выбери vc-gui.exe. "
                "При первом запуске движок предложит подготовить служебные модели; "
                "также понадобится собственная RVC-модель голоса."
            )
            webbrowser.open("https://github.com/shirohata/vc-rs/releases")
            selected = filedialog.askopenfilename(
                title="Выбери vc-gui.exe из распакованного пакета vc-rs",
                filetypes=[("Windows executable", "*.exe")],
            )
            if not selected:
                return
            executable = Path(selected)
            if executable.name.lower() != "vc-gui.exe":
                messagebox.showerror("Voice Reader Pro", "Нужно выбрать именно vc-gui.exe.")
                return
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                config_path.write_text(str(executable.resolve()), encoding="utf-8")
            except OSError as exc:
                messagebox.showwarning("Voice Reader Pro", f"Не удалось сохранить путь к AI-приложению: {exc}")
        try:
            self.ai_process = subprocess.Popen([str(executable)], cwd=str(executable.parent))
            self.status.set("Запущено отдельное AI-приложение RVC")
        except Exception as exc:
            messagebox.showerror("Voice Reader Pro", f"Не удалось запустить AI-преобразование: {exc}")

    def refresh_devices(self):
        try:
            self.devices = list_audio_devices()
        except Exception as exc:
            self.devices = []
            self.status.set(f"Аудиоустройства недоступны: {exc}")
            self.input_combo["values"] = ()
            self.output_combo["values"] = ()
            return

        self.input_lookup = {}
        self.output_lookup = {}
        inputs, outputs = [], []
        for device in self.devices:
            label = f'{device["index"]} — {device["name"]}'
            if device["inputs"] > 0:
                inputs.append(label)
                self.input_lookup[label] = device
            if device["outputs"] > 0:
                outputs.append(label)
                self.output_lookup[label] = device
        self.input_combo["values"] = inputs
        self.output_combo["values"] = outputs
        if inputs and self.input_var.get() not in self.input_lookup:
            preferred = next((x for x in inputs if "microphone" in x.lower() or "микрофон" in x.lower()), inputs[0])
            self.input_var.set(preferred)
        if outputs and self.output_var.get() not in self.output_lookup:
            cable = next((x for x in outputs if "cable input" in x.lower() or "vb-audio" in x.lower()), None)
            self.output_var.set(cable or outputs[0])
        if not inputs or not outputs:
            self.status.set("Не найдены устройства ввода или вывода.")

    def select_preset(self, name: str):
        try:
            self.engine.configure(name)
            settings = PRESETS[name]
            for key, variable in self.values.items():
                variable.set(float(settings.get(key, 0.0)))
                self._update_value_label(key)
            self.selected_preset.set(f"Выбран эффект: {name}")
            self.status.set("Эффект выбран")
        except Exception as exc:
            messagebox.showerror("Voice Reader Pro", f"Не удалось применить эффект: {exc}")

    def _update_value_label(self, key: str):
        label, suffix = self.value_labels[key]
        value = self.values[key].get()
        label.configure(text=f"{value:+.1f}{suffix}")

    def _slider_changed(self, key: str, value: str):
        self._update_value_label(key)
        self.selected_preset.set("Выбран эффект: Ручная настройка")
        if not hasattr(self, "engine"):
            return
        settings = {name: variable.get() for name, variable in self.values.items()}
        settings["radio"] = False
        try:
            self.engine.configure("Обычный", settings)
        except Exception as exc:
            self.last_ui_error = str(exc)

    def toggle(self):
        if self.engine.running:
            self.stop()
            return
        input_device = self.input_lookup.get(self.input_var.get())
        output_device = self.output_lookup.get(self.output_var.get())
        if not input_device or not output_device:
            messagebox.showwarning("Voice Reader Pro", "Выбери микрофон и устройство вывода.")
            return
        output_name = output_device["name"].lower()
        if "cable input" not in output_name and "vb-audio" not in output_name:
            messagebox.showwarning(
                "Voice Reader Pro",
                "Выбери CABLE Input (VB-Audio Virtual Cable). Иначе обработанный звук не появится как виртуальный микрофон."
            )
            return
        try:
            self.engine.start(input_device["index"], output_device["index"])
            self.start_button.configure(text="■  Выключить голосовой эффект")
            self.status.set(f"Работает · {self.engine._sample_rate // 1000} кГц")
        except Exception as exc:
            self.engine.stop()
            messagebox.showerror("Voice Reader Pro", f"Не удалось запустить микрофон: {exc}")
            self.status.set("Не удалось запустить аудио")

    def stop(self):
        try:
            self.engine.stop()
        finally:
            self.start_button.configure(text="▶  Включить голосовой эффект")
            self.status.set("Остановлено")

    def _schedule_poll(self):
        self._poll_job = self.root.after(250, self._poll)
    def _poll(self):
        self._poll_job = None
        if self.engine.last_error:
            error = self.engine.last_error
            try:
                self.engine.stop()
            finally:
                self.start_button.configure(text="▶  Включить голосовой эффект")
                self.status.set(f"Ошибка обработки: {error}")
        elif self.engine.last_status and self.engine.running:
            self.status.set(f"Работает · {self.engine.last_status}")
        if self.ai_process is not None and self.ai_process.poll() is not None:
            self.ai_process = None
            if not self.engine.running:
                self.status.set("AI-приложение закрыто")
        if self.root.winfo_exists():
            self._schedule_poll()

    def back(self):
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        if self.engine.running:
            self.stop()
        self.engine.close()
        if self.on_back:
            self.on_back()

    def close(self):
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        self.engine.close()
        if self.ai_process is not None and self.ai_process.poll() is None:
            try:
                self.ai_process.terminate()
            except Exception:
                pass
        self.root.destroy()
