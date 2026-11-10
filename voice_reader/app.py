import asyncio
import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
import keyring
from voice_reader.core import VoiceService
from voice_reader.voice_profiles import (
    VOICE_PRESETS,
    VOICE_PRESET_LABELS,
    VOICE_LABEL_TO_PRESET,
    LEGACY_VOICE_IDS,
)

APP_NAME, TOKEN_KEY = 'Voice Reader Pro', 'discord-token'
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
VOICE_ASSETS = APP_DIR / 'voices'
VOICE_MODEL = VOICE_ASSETS / 'v5_6_ru.pt'
DATA = Path(os.getenv('APPDATA', Path.home())) / 'VoiceReaderPro'
CONFIG = DATA / 'config.json'

def tool(name):
    suffix = '.exe' if os.name == 'nt' else ''
    bundled = ROOT / f'{name}{suffix}'
    return str(bundled if bundled.exists() else shutil.which(name) or '')

class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.geometry('920x760')
        root.minsize(780, 650)
        root.configure(bg='#090d18')

        self.events = queue.Queue()
        self.thread = self.loop = self.service = None
        self.pasting = False
        DATA.mkdir(parents=True, exist_ok=True)
        cfg = self.load()

        style = ttk.Style(root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        BG = '#090d18'
        PANEL = '#121a2b'
        FIELD = '#0b1322'
        TEXT = '#edf2ff'
        MUTED = '#93a0b6'
        PURPLE = '#887cff'
        BORDER = '#26334b'

        style.configure('Shell.TFrame', background=BG)
        style.configure('Card.TFrame', background=PANEL)
        style.configure('Title.TLabel', background=BG, foreground=TEXT,
                        font=('Segoe UI', 22, 'bold'))
        style.configure('Subtitle.TLabel', background=BG, foreground=MUTED,
                        font=('Segoe UI', 10))
        style.configure('CardTitle.TLabel', background=PANEL, foreground=TEXT,
                        font=('Segoe UI', 13, 'bold'))
        style.configure('Field.TLabel', background=PANEL, foreground='#aebbd0',
                        font=('Segoe UI', 9, 'bold'))
        style.configure('Muted.TLabel', background=PANEL, foreground=MUTED,
                        font=('Segoe UI', 9))
        style.configure('Status.TLabel', background=PANEL, foreground='#a6f0d2',
                        font=('Segoe UI', 9, 'bold'))
        style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, padding=9)
        style.configure('TCombobox', fieldbackground=FIELD, background=FIELD,
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, padding=8)
        style.map('TCombobox',
                  fieldbackground=[('readonly', FIELD), ('focus', FIELD)],
                  foreground=[('readonly', TEXT)])
        style.configure('Primary.TButton', background=PURPLE, foreground='white',
                        font=('Segoe UI', 10, 'bold'), padding=(17, 10), borderwidth=0)
        style.map('Primary.TButton',
                  background=[('disabled', '#4c4a70'), ('active', '#9a90ff')],
                  foreground=[('disabled', '#c4c1da')])
        style.configure('Secondary.TButton', background='#26334b', foreground=TEXT,
                        font=('Segoe UI', 10, 'bold'), padding=(15, 10), borderwidth=0)
        style.map('Secondary.TButton', background=[('active', '#33435f')])
        style.configure('Copy.TButton', background='#202d43', foreground=TEXT,
                        font=('Segoe UI', 9, 'bold'), padding=(12, 8), borderwidth=0)
        style.map('Copy.TButton', background=[('active', '#33435f')])

        outer = ttk.Frame(root, style='Shell.TFrame', padding=(24, 20))
        outer.pack(fill='both', expand=True)

        header = ttk.Frame(outer, style='Shell.TFrame')
        header.pack(fill='x', pady=(0, 18))
        heading = ttk.Frame(header, style='Shell.TFrame')
        heading.pack(side='left', fill='x', expand=True)
        ttk.Label(heading, text='Voice Reader Pro', style='Title.TLabel').pack(anchor='w')
        ttk.Label(
            heading,
            text='Локальная озвучка текста в голосовом канале Discord',
            style='Subtitle.TLabel',
        ).pack(anchor='w', pady=(4, 0))

        self.status = tk.StringVar(value='Остановлено')
        self.status_label = ttk.Label(header, textvariable=self.status, style='Status.TLabel')
        self.status_label.pack(side='right', anchor='n', padx=(10, 0), pady=7)

        card = ttk.Frame(outer, style='Card.TFrame', padding=20)
        card.pack(fill='x')
        ttk.Label(card, text='Подключение', style='CardTitle.TLabel').pack(anchor='w', pady=(0, 15))

        self.fields = {}

        def add_field(parent, label, key, show='', row=0, column=0, columnspan=1):
            cell = ttk.Frame(parent, style='Card.TFrame')
            cell.grid(row=row, column=column, columnspan=columnspan,
                      sticky='ew', padx=(0 if column == 0 else 10, 0), pady=(0, 12))
            ttk.Label(cell, text=label, style='Field.TLabel').pack(anchor='w', pady=(0, 6))
            if key == 'voice':
                entry = ttk.Combobox(
                    cell,
                    values=list(VOICE_PRESET_LABELS.values()),
                    state='readonly',
                )
                configured_voice = cfg.get('voice', 'normal')
                preset_key = LEGACY_VOICE_IDS.get(configured_voice, configured_voice)
                entry.set(VOICE_PRESET_LABELS.get(preset_key, VOICE_PRESETS['normal']['label']))
            else:
                entry = ttk.Entry(cell, show=show)
                entry.insert(0, cfg.get(key, ''))
            entry.pack(fill='x')
            self.fields[key] = entry

        fields_grid = ttk.Frame(card, style='Card.TFrame')
        fields_grid.pack(fill='x')
        fields_grid.columnconfigure(0, weight=1)
        fields_grid.columnconfigure(1, weight=1)

        add_field(fields_grid, 'ТОКЕН DISCORD-БОТА', 'token', show='•', row=0, column=0, columnspan=2)
        add_field(fields_grid, 'ID СЕРВЕРА', 'guild_id', row=1, column=0)
        add_field(fields_grid, 'ID ГОЛОСОВОГО КАНАЛА', 'channel_id', row=1, column=1)
        add_field(fields_grid, 'ГОЛОС ПО УМОЛЧАНИЮ', 'voice', row=2, column=0, columnspan=2)

        controls = ttk.Frame(card, style='Card.TFrame')
        controls.pack(fill='x', pady=(2, 6))
        self.start = ttk.Button(controls, text='▶  Запустить', style='Primary.TButton',
                                command=self.start_service)
        self.start.pack(side='left')
        self.stop = ttk.Button(controls, text='■  Остановить', style='Secondary.TButton',
                               command=self.stop_service, state='disabled')
        self.stop.pack(side='left', padx=(10, 0))

        ttk.Label(card, text='ПУБЛИЧНАЯ ССЫЛКА', style='Field.TLabel').pack(anchor='w', pady=(14, 6))
        link_row = ttk.Frame(card, style='Card.TFrame')
        link_row.pack(fill='x')
        self.link = ttk.Entry(link_row)
        self.link.pack(side='left', fill='x', expand=True)
        ttk.Button(link_row, text='Копировать', style='Copy.TButton',
                   command=self.copy).pack(side='left', padx=(10, 0))

        log_card = ttk.Frame(outer, style='Card.TFrame', padding=16)
        log_card.pack(fill='both', expand=True, pady=(16, 0))
        log_header = ttk.Frame(log_card, style='Card.TFrame')
        log_header.pack(fill='x', pady=(0, 9))
        ttk.Label(log_header, text='Журнал работы', style='CardTitle.TLabel').pack(side='left')
        ttk.Label(log_header, text='События Discord · TTS · сервера',
                  style='Muted.TLabel').pack(side='right')

        self.log = tk.Text(
            log_card,
            height=12,
            state='disabled',
            bg='#080e19',
            fg='#c9d5e8',
            insertbackground=TEXT,
            selectbackground='#4b4f83',
            selectforeground='white',
            relief='flat',
            borderwidth=0,
            padx=12,
            pady=10,
            wrap='word',
            font=('Consolas', 9),
        )
        self.log.pack(fill='both', expand=True)

        footer = ttk.Label(
            outer,
            text='Голоса хранятся локально в папке voices. Для сайта можно выбирать диктора отдельно для каждого сообщения.',
            style='Subtitle.TLabel',
        )
        footer.pack(anchor='w', pady=(12, 0))

        # Per-entry paste handlers: no global binding, so a paste is applied once.
        for entry in [*self.fields.values(), self.link]:
            entry.bind('<Control-KeyPress>', self.handle_entry_control)
            entry.bind('<Shift-Insert>', self.paste_entry)
            entry.bind('<Button-3>', self.show_entry_menu)

        root.after(200, self.drain)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def load(self):
        try:
            cfg = json.loads(CONFIG.read_text('utf-8'))
        except Exception:
            cfg = {}
        try:
            cfg['token'] = keyring.get_password(APP_NAME, TOKEN_KEY) or ''
        except Exception:
            cfg['token'] = ''
        return cfg

    def save(self):
        settings = {
            k: self.fields[k].get().strip()
            for k in ('guild_id', 'channel_id')
        }
        selected_label = self.fields['voice'].get().strip()
        settings['voice'] = VOICE_LABEL_TO_PRESET.get(selected_label, 'normal')
        CONFIG.write_text(json.dumps(settings, ensure_ascii=False, indent=2), 'utf-8')
        keyring.set_password(APP_NAME, TOKEN_KEY, self.fields['token'].get().strip())

    def emit(self, msg):
        self.events.put(('log', msg))

    def drain(self):
        try:
            while True:
                typ, msg = self.events.get_nowait()
                if typ == 'log':
                    self.log.configure(state='normal')
                    self.log.insert('end', msg + '\n')
                    self.log.see('end')
                    self.log.configure(state='disabled')
                elif typ == 'url':
                    self.link.delete(0, 'end')
                    self.link.insert(0, msg)
                    self.status.set('Работает')
                elif typ == 'error':
                    self.status.set('Ошибка')
                    messagebox.showerror(APP_NAME, msg)
                    self.start.configure(state='normal')
                    self.stop.configure(state='disabled')
        except queue.Empty:
            pass
        self.root.after(200, self.drain)

    def start_service(self):
        # WinRAR's Open action may run an onedir build from a temporary folder,
        # where only part of _internal is extracted.
        # The literal path marker "rar$" identifies WinRAR temporary extraction folders.
        rarMarker = 'rar' + '$'
        if getattr(sys, 'frozen', False) and rarMarker in str(Path(sys.executable).resolve()).casefold():
            messagebox.showerror(
                APP_NAME,
                'Программа запущена прямо из временной папки WinRAR.\\n\\n'
                'Закройте её, вернитесь к ZIP-архиву, нажмите «Извлечь всё» и запускайте '
                'VoiceReaderPro.exe только из полностью распакованной папки. Рядом с EXE '
                'должны находиться папки _internal и voices.',
            )
            return

        token = self.fields['token'].get().strip()
        guild = self.fields['guild_id'].get().strip()
        channel = self.fields['channel_id'].get().strip()
        if not token or not guild.isdigit() or not channel.isdigit():
            return messagebox.showwarning(APP_NAME, 'Введите токен и числовые ID сервера и голосового канала.')
        ffmpeg, cloudflared = tool('ffmpeg'), tool('cloudflared')
        if not ffmpeg or not cloudflared:
            return messagebox.showerror(APP_NAME, 'Не найдены встроенные FFmpeg или cloudflared.')
        required_voice_files = (
            VOICE_MODEL,
            VOICE_ASSETS / 'armenian' / 'armenian_tri.yaml',
            VOICE_ASSETS / 'armenian' / 'armenian_reference.wav',
            VOICE_ASSETS / 'armenian' / 'tri_v1' / 'model.safetensors',
            VOICE_ASSETS / 'teratts' / 'teratts.py',
            VOICE_ASSETS / 'teratts' / 'models' / 'text_encoder.onnx',
            VOICE_ASSETS / 'teratts' / 'styles' / 'ru_m5' / 'style_ttl.npy',
        )
        missing_voice_files = [path for path in required_voice_files if not path.is_file()]
        if missing_voice_files:
            return messagebox.showerror(
                APP_NAME,
                'Не найдены файлы армянского или поп-голоса. Распакуйте ZIP полностью: '
                'рядом с VoiceReaderPro.exe должна быть папка voices.',
            )
        try:
            self.save()
        except Exception as e:
            return messagebox.showerror(APP_NAME, f'Не удалось безопасно сохранить токен: {e}')
        self.start.configure(state='disabled')
        self.stop.configure(state='normal')
        self.status.set('Запуск…')
        selected_voice_label = self.fields['voice'].get().strip()
        voice_preset = VOICE_LABEL_TO_PRESET.get(selected_voice_label, 'normal')
        self.thread = threading.Thread(target=self.run,
            args=(token, guild, channel, voice_preset, ffmpeg, cloudflared), daemon=True)
        self.thread.start()

    def run(self, *args):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run_async(*args))

    async def run_async(self, token, guild, channel, voice, ffmpeg, cloudflared):
        try:
            self.service = VoiceService(token, guild, channel, voice, ffmpeg, self.emit, VOICE_MODEL)
            await self.service.start()
            p = await asyncio.create_subprocess_exec(cloudflared, 'tunnel', '--url',
                'http://127.0.0.1:8765', '--no-autoupdate',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            self.service.tunnel = p
            while True:
                line = (await p.stdout.readline()).decode(errors='replace')
                if not line:
                    break
                self.emit(line.strip())
                if 'trycloudflare.com' in line:
                    import re
                    url = re.search(r'https://[^\s]+trycloudflare\.com', line)
                    if url:
                        self.events.put(('url', url.group(0)))
        except Exception as e:
            self.events.put(('error', str(e)))
        finally:
            if self.service:
                await self.service.stop()

    def stop_service(self):
        self.status.set('Остановка…')
        if self.loop and self.service:
            if self.service.tunnel:
                self.service.tunnel.terminate()
            asyncio.run_coroutine_threadsafe(self.service.stop(), self.loop)
        self.start.configure(state='normal')
        self.stop.configure(state='disabled')
        self.status.set('Остановлено')

    def copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.link.get())

    def paste_entry(self, event=None):
        widget = event.widget if event is not None else self.root.focus_get()
        if widget is None:
            return 'break'
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            return 'break'
        try:
            if widget.selection_present():
                widget.delete('sel.first', 'sel.last')
        except (tk.TclError, AttributeError):
            pass
        try:
            widget.insert('insert', value)
        except tk.TclError:
            pass
        return 'break'

    def handle_entry_control(self, event):
        # Windows keycode 86 is the physical V key, including Russian keyboard layout.
        if event.state & 0x4 and event.keycode == 86:
            return self.paste_entry(event)
        return None

    def show_entry_menu(self, event):
        widget = event.widget
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label='Вставить', command=lambda: self.paste_entry_for(widget))
        menu.add_command(label='Копировать', command=lambda: widget.event_generate('<<Copy>>'))
        menu.add_command(label='Вырезать', command=lambda: widget.event_generate('<<Cut>>'))
        menu.add_separator()
        menu.add_command(label='Выделить всё', command=lambda: widget.select_range(0, 'end'))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def paste_entry_for(self, widget):
        class PasteEvent:
            pass
        event = PasteEvent()
        event.widget = widget
        self.paste_entry(event)

    def close(self):
        self.stop_service()
        self.root.destroy()

def run_frozen_voice_smoke_test(preset: str) -> int:
    """Synthesize one voice through the actual PyInstaller executable."""
    import gc
    import tempfile
    import traceback
    import wave

    from voice_reader.additional_tts import ArmenianAccentTTS, TeraPopTTS
    from voice_reader.local_tts import LocalSileroTTS
    from voice_reader.voice_profiles import resolve_voice_profile

    log_path = Path(tempfile.gettempdir()) / f"VoiceReaderPro-smoke-{preset}.log"
    output_path = Path(tempfile.gettempdir()) / f"VoiceReaderPro-smoke-{preset}.wav"

    def log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(str(message) + chr(10))

    log_path.write_text(f"Frozen EXE voice smoke test: {preset}" + chr(10), encoding="utf-8")
    output_path.unlink(missing_ok=True)
    try:
        profile = resolve_voice_profile(preset)
        engine = profile["engine"]
        sample_text = "Привет! Проверка голоса в собранном приложении Voice Reader Pro."

        if engine == "silero":
            tts = LocalSileroTTS(VOICE_MODEL, log)
            tts.load()
            size, duration = tts.synthesize_to_wav(sample_text, profile["speaker"], output_path)
            del tts
        elif engine == "armenian":
            tts = ArmenianAccentTTS(VOICE_ASSETS / "armenian", log)
            size, duration = tts.synthesize_to_wav(sample_text, output_path)
            tts.unload()
            del tts
        elif engine == "teratts":
            tts = TeraPopTTS(VOICE_ASSETS / "teratts", log)
            size, duration = tts.synthesize_to_wav(sample_text, output_path)
            tts.unload()
            del tts
        else:
            raise RuntimeError(f"Unsupported voice engine in frozen test: {engine}")

        with wave.open(str(output_path), "rb") as audio:
            actual_duration = audio.getnframes() / float(audio.getframerate())
        if size < 2048 or duration < 0.25 or actual_duration < 0.25:
            raise RuntimeError(
                f"Invalid generated audio: bytes={size}, duration={duration:.2f}s, "
                f"wav_duration={actual_duration:.2f}s"
            )
        log(f"PASS: {preset}; engine={engine}; {duration:.2f}s; {size} bytes.")
        return 0
    except Exception:
        log("FAIL: " + traceback.format_exc())
        return 1
    finally:
        output_path.unlink(missing_ok=True)
        gc.collect()


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == '--voice-smoke-test':
        raise SystemExit(run_frozen_voice_smoke_test(sys.argv[2]))
    App(tk.Tk()).root.mainloop()
