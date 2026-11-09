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
from voice_reader.core import (
    VoiceService,
    VOICE_PRESETS,
    VOICE_PRESET_LABELS,
    VOICE_LABEL_TO_PRESET,
    LEGACY_VOICE_IDS,
)

APP_NAME, TOKEN_KEY = 'Voice Reader Pro', 'discord-token'
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
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
        root.geometry('650x540')
        self.events = queue.Queue()
        self.thread = self.loop = self.service = None
        self.pasting = False
        DATA.mkdir(parents=True, exist_ok=True)
        cfg = self.load()
        box = ttk.Frame(root, padding=16)
        box.pack(fill='both', expand=True)
        self.fields = {}
        for label, key, show in [
            ('Токен Discord-бота', 'token', '•'),
            ('ID сервера', 'guild_id', ''),
            ('ID голосового канала', 'channel_id', ''),
            ('Голос озвучивания', 'voice', '')
        ]:
            ttk.Label(box, text=label).pack(anchor='w')
            if key == 'voice':
                e = ttk.Combobox(
                    box,
                    values=list(VOICE_PRESET_LABELS.values()),
                    state='readonly',
                )
                configured_voice = cfg.get('voice', 'dmitry')
                preset_key = LEGACY_VOICE_IDS.get(configured_voice, configured_voice)
                e.set(VOICE_PRESET_LABELS.get(preset_key, VOICE_PRESETS['dmitry']['label']))
            else:
                e = ttk.Entry(box, show=show)
                e.insert(0, cfg.get(key, ''))
            e.pack(fill='x', pady=(0, 8))
            self.fields[key] = e
        row = ttk.Frame(box)
        row.pack(fill='x', pady=8)
        self.start = ttk.Button(row, text='Запустить', command=self.start_service)
        self.start.pack(side='left')
        self.stop = ttk.Button(row, text='Остановить', command=self.stop_service, state='disabled')
        self.stop.pack(side='left', padx=8)
        ttk.Label(box, text='Публичная ссылка').pack(anchor='w')
        self.link = ttk.Entry(box)
        self.link.pack(fill='x')
        ttk.Button(box, text='Копировать ссылку', command=self.copy).pack(anchor='w', pady=6)
        self.status = tk.StringVar(value='Остановлено')
        ttk.Label(box, textvariable=self.status).pack(anchor='w')
        self.log = tk.Text(box, height=8, state='disabled')
        self.log.pack(fill='both', expand=True)
        # Per-entry paste handlers: no global binding, so a paste is applied once.
        for entry in [*self.fields.values(), self.link]:
            entry.bind('<Control-KeyPress>', self.handle_entry_control)
            entry.bind('<Shift-Insert>', self.paste_entry)
            entry.bind('<Button-3>', self.show_entry_menu)
        # Let Tkinter's native class binding handle Ctrl+V exactly once.
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
        settings['voice'] = VOICE_LABEL_TO_PRESET.get(selected_label, 'dmitry')
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
        token = self.fields['token'].get().strip()
        guild = self.fields['guild_id'].get().strip()
        channel = self.fields['channel_id'].get().strip()
        if not token or not guild.isdigit() or not channel.isdigit():
            return messagebox.showwarning(APP_NAME, 'Введите токен и числовые ID сервера и голосового канала.')
        ffmpeg, cloudflared = tool('ffmpeg'), tool('cloudflared')
        if not ffmpeg or not cloudflared:
            return messagebox.showerror(APP_NAME, 'Не найдены встроенные FFmpeg или cloudflared.')
        try:
            self.save()
        except Exception as e:
            return messagebox.showerror(APP_NAME, f'Не удалось безопасно сохранить токен: {e}')
        self.start.configure(state='disabled')
        self.stop.configure(state='normal')
        self.status.set('Запуск…')
        selected_voice_label = self.fields['voice'].get().strip()
        voice_preset = VOICE_LABEL_TO_PRESET.get(selected_voice_label, 'dmitry')
        self.thread = threading.Thread(target=self.run,
            args=(token, guild, channel, voice_preset, ffmpeg, cloudflared), daemon=True)
        self.thread.start()

    def run(self, *args):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run_async(*args))

    async def run_async(self, token, guild, channel, voice, ffmpeg, cloudflared):
        try:
            self.service = VoiceService(token, guild, channel, voice, ffmpeg, self.emit)
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

if __name__ == '__main__':
    App(tk.Tk()).root.mainloop()
