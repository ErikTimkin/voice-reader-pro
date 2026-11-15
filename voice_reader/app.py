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
        root.geometry('760x650')
        root.minsize(680, 560)
        root.option_add('*Font', ('Segoe UI', 9))
        root.configure(bg='#090d18')

        self.events = queue.Queue()
        self.stop_requested = threading.Event()
        self.thread = self.loop = self.service = None
        self.keep_awake = False
        self._keep_awake_job = None
        DATA.mkdir(parents=True, exist_ok=True)
        cfg = self.load()

        style = ttk.Style(root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        BG, PANEL, FIELD = '#090d18', '#121a2b', '#0b1322'
        TEXT, MUTED, PURPLE, BORDER = '#edf2ff', '#93a0b6', '#887cff', '#26334b'
        style.configure('Shell.TFrame', background=BG)
        style.configure('Card.TFrame', background=PANEL)
        style.configure('Title.TLabel', background=BG, foreground=TEXT, font=('Segoe UI', 23, 'bold'))
        style.configure('Subtitle.TLabel', background=BG, foreground=MUTED, font=('Segoe UI', 10))
        style.configure('CardTitle.TLabel', background=PANEL, foreground=TEXT, font=('Segoe UI', 13, 'bold'))
        style.configure('Field.TLabel', background=PANEL, foreground='#aebbd0', font=('Segoe UI', 9, 'bold'))
        style.configure('Muted.TLabel', background=PANEL, foreground=MUTED, font=('Segoe UI', 9))
        style.configure('Status.TLabel', background=BG, foreground='#a6f0d2', font=('Segoe UI', 10, 'bold'))
        style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=10)
        style.configure('Primary.TButton', background=PURPLE, foreground='white',
                        font=('Segoe UI', 14, 'bold'), padding=(28, 20), borderwidth=0)
        style.map('Primary.TButton', background=[('disabled', '#4c4a70'), ('active', '#9a90ff')])
        style.configure('Secondary.TButton', background='#26334b', foreground=TEXT,
                        font=('Segoe UI', 10, 'bold'), padding=(18, 12), borderwidth=0)
        style.map('Secondary.TButton', background=[('active', '#33435f')])
        style.configure('Copy.TButton', background='#202d43', foreground=TEXT,
                        font=('Segoe UI', 9, 'bold'), padding=(12, 8), borderwidth=0)
        style.map('Copy.TButton', background=[('active', '#33435f')])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED,
                        padding=(18, 10), font=('Segoe UI', 9, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', '#26334b')],
                  foreground=[('selected', TEXT)])

        outer = ttk.Frame(root, style='Shell.TFrame', padding=(24, 20))
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer, style='Shell.TFrame')
        header.pack(fill='x', pady=(0, 18))
        ttk.Label(header, text='Voice Reader Pro', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='Голосовой помощник для Discord', style='Subtitle.TLabel').pack(anchor='w', pady=(4, 0))

        self.status = tk.StringVar(value='Остановлено')
        ttk.Label(header, textvariable=self.status, style='Status.TLabel').pack(anchor='e', pady=(8, 0))

        self.service_states = {
            'discord': tk.StringVar(value='Не запущен'),
            'web': tk.StringVar(value='Не запущен'),
            'tunnel': tk.StringVar(value='Не создана'),
        }
        notebook = ttk.Notebook(outer)
        notebook.pack(fill='both', expand=True)
        self.notebook = notebook
        home_tab = ttk.Frame(notebook, style='Shell.TFrame', padding=(18, 28))
        server_tab = ttk.Frame(notebook, style='Shell.TFrame', padding=(18, 18))
        notebook.add(home_tab, text='Главная')
        notebook.add(server_tab, text='Сервер')

        home_content = ttk.Frame(home_tab, style='Shell.TFrame')
        home_content.pack(expand=True, fill='both')
        ttk.Label(home_content, text='Готов к запуску?', style='Title.TLabel').pack(pady=(38, 10))
        ttk.Label(home_content, text='Запусти бота — он подключится к голосовому каналу и откроет страницу озвучки.',
                  style='Subtitle.TLabel', wraplength=480, justify='center').pack(pady=(0, 28))
        self.start = ttk.Button(home_content, text='▶  Запустить бота',
                                style='Primary.TButton', command=self.start_service)
        self.start.pack(fill='x', padx=55, pady=(0, 22))
        ttk.Button(home_content, text='⚙  Сервер',
                   style='Secondary.TButton', command=lambda: notebook.select(server_tab)).pack()
        ttk.Label(home_content, textvariable=self.service_states['discord'],
                  style='Subtitle.TLabel').pack(pady=(24, 0))

        server_card = ttk.Frame(server_tab, style='Card.TFrame', padding=20)
        server_card.pack(fill='x')
        ttk.Label(server_card, text='Подключение Discord', style='CardTitle.TLabel').pack(anchor='w', pady=(0, 16))
        self.fields = {}
        fields_grid = ttk.Frame(server_card, style='Card.TFrame')
        fields_grid.pack(fill='x')
        fields_grid.columnconfigure(0, weight=1)
        fields_grid.columnconfigure(1, weight=1)

        def add_field(parent, label, key, show='', row=0, column=0, columnspan=1):
            cell = ttk.Frame(parent, style='Card.TFrame')
            cell.grid(row=row, column=column, columnspan=columnspan,
                      sticky='ew', padx=(0 if column == 0 else 10, 0), pady=(0, 13))
            ttk.Label(cell, text=label, style='Field.TLabel').pack(anchor='w', pady=(0, 6))
            entry = ttk.Entry(cell, show=show)
            entry.insert(0, cfg.get(key, ''))
            entry.pack(fill='x')
            self.fields[key] = entry

        add_field(fields_grid, 'ТОКЕН DISCORD-БОТА', 'token', show='•', row=0, column=0, columnspan=2)
        add_field(fields_grid, 'ID СЕРВЕРА', 'guild_id', row=1, column=0)
        add_field(fields_grid, 'ID ГОЛОСОВОГО КАНАЛА', 'channel_id', row=1, column=1)
        save_row = ttk.Frame(server_card, style='Card.TFrame')
        save_row.pack(fill='x', pady=(2, 0))
        ttk.Button(save_row, text='Сохранить настройки', style='Secondary.TButton',
                   command=self.save_settings).pack(anchor='w')

        status_card = ttk.Frame(server_tab, style='Card.TFrame', padding=16)
        status_card.pack(fill='x', pady=(12, 0))
        ttk.Label(status_card, text='Состояние сервисов', style='CardTitle.TLabel').pack(anchor='w', pady=(0, 10))
        for key, title in (('discord', 'DISCORD'), ('web', 'ЛОКАЛЬНЫЙ СЕРВЕР'), ('tunnel', 'ПУБЛИЧНАЯ ССЫЛКА')):
            line = ttk.Frame(status_card, style='Card.TFrame')
            line.pack(fill='x', pady=3)
            ttk.Label(line, text=title, style='Field.TLabel', width=22).pack(side='left')
            ttk.Label(line, textvariable=self.service_states[key], style='Muted.TLabel').pack(side='left')

        link_card = ttk.Frame(server_tab, style='Card.TFrame', padding=16)
        link_card.pack(fill='x', pady=(12, 0))
        ttk.Label(link_card, text='Публичная ссылка сайта', style='CardTitle.TLabel').pack(anchor='w', pady=(0, 8))
        link_row = ttk.Frame(link_card, style='Card.TFrame')
        link_row.pack(fill='x')
        self.link = ttk.Entry(link_row)
        self.link.pack(side='left', fill='x', expand=True)
        ttk.Button(link_row, text='Копировать', style='Copy.TButton', command=self.copy).pack(side='left', padx=(10, 0))

        log_card = ttk.Frame(server_tab, style='Card.TFrame', padding=14)
        log_card.pack(fill='both', expand=True, pady=(12, 0))
        log_header = ttk.Frame(log_card, style='Card.TFrame')
        log_header.pack(fill='x', pady=(0, 8))
        ttk.Label(log_header, text='Журнал работы', style='CardTitle.TLabel').pack(side='left')
        ttk.Button(log_header, text='Очистить', style='Copy.TButton', command=self.clear_log).pack(side='right')
        ttk.Button(log_header, text='Копировать журнал', style='Copy.TButton', command=self.copy_log).pack(side='right', padx=(0, 8))
        log_body = ttk.Frame(log_card, style='Card.TFrame')
        log_body.pack(fill='both', expand=True)
        self.log_body = log_body
        self.log = tk.Text(log_body, height=9, state='normal', bg='#080e19', fg='#c9d5e8',
                           insertbackground=TEXT, selectbackground='#4b4f83',
                           selectforeground='white', relief='flat', borderwidth=0,
                           padx=12, pady=10, wrap='word', font=('Consolas', 9))
        self.log.pack(side='left', fill='both', expand=True)
        log_scroll = ttk.Scrollbar(log_body, orient='vertical', command=self.log.yview)
        log_scroll.pack(side='right', fill='y')
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.bind('<Key>', self.protect_log)
        self.log.bind('<Control-a>', self.select_all_log)
        self.log.bind('<Control-A>', self.select_all_log)
        self.log.bind('<Button-3>', self.show_log_menu)

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
        CONFIG.write_text(json.dumps(settings, ensure_ascii=False, indent=2), 'utf-8')
        keyring.set_password(APP_NAME, TOKEN_KEY, self.fields['token'].get().strip())

    def save_settings(self):
        try:
            self.save()
            messagebox.showinfo(APP_NAME, 'Настройки сервера сохранены.')
        except Exception as exc:
            messagebox.showerror(APP_NAME, f'Не удалось сохранить настройки: {exc}')

    def emit(self, msg):
        self.events.put(('log', msg))

    def drain(self):
        try:
            while True:
                typ, msg = self.events.get_nowait()
                if typ == 'log':
                    self.log.insert('end', msg + '\n')
                    self.log.see('end')
                elif typ == 'url':
                    self.link.delete(0, 'end')
                    self.link.insert(0, msg)
                    self.status.set('Работает')
                elif typ == 'state':
                    key, value = msg
                    if key in self.service_states:
                        self.service_states[key].set(value)
                elif typ == 'error':
                    self.status.set('Ошибка')
                    self.log.insert('end', f'ОШИБКА ЗАПУСКА: {msg}\n')
                    self.log.see('end')
                    messagebox.showerror(APP_NAME, msg)
                    self.start.configure(text='▶  Запустить бота', command=self.start_service, state='normal')
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
        try:
            self.save()
        except Exception as e:
            return messagebox.showerror(APP_NAME, f'Не удалось безопасно сохранить токен: {e}')
        self.stop_requested.clear()
        self._set_system_awake(True)
        for key in self.service_states:
            self.service_states[key].set('Запуск…')
        self.link.delete(0, 'end')
        self.start.configure(text='■  Остановить бота', command=self.stop_service, state='normal')
        self.status.set('Запуск…')
        self.thread = threading.Thread(
            target=self.run,
            args=(token, guild, channel, 'normal', ffmpeg, cloudflared),
            daemon=True,
        )
        self.thread.start()

    def run(self, *args):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            while not self.stop_requested.is_set():
                try:
                    self.loop.run_until_complete(self.run_async(*args))
                except Exception as exc:
                    if self.stop_requested.is_set():
                        break
                    self.emit(
                        f"Критическая ошибка сервиса: {type(exc).__name__}: {exc}. "
                        "Перезапускаю Discord и веб-сервер через 5 секунд…"
                    )
                    self.stop_requested.wait(5)
        finally:
            if self.loop is not None and not self.loop.is_closed():
                self.loop.close()
            self.loop = None

    async def run_async(self, token, guild, channel, voice, ffmpeg, cloudflared):
        try:
            self.service = VoiceService(token, guild, channel, voice, ffmpeg, self.emit, VOICE_MODEL)
            await self.service.start()
            self.events.put(('state', ('web', 'Работает · 127.0.0.1:8765')))
            self.events.put(('state', ('discord', 'Подключение…')))
            status_task = asyncio.create_task(self._watch_service_status())
            retry_delay = 2

            # A quick Cloudflare tunnel is only the public web entry point.
            # Its temporary process may exit independently of Discord/TTS;
            # keep the local service and bot alive while reconnecting it.
            while not self.stop_requested.is_set():
                process = None
                try:
                    # HTTP/2 is more reliable than QUIC on networks that block UDP.
                    process = await asyncio.create_subprocess_exec(
                        cloudflared,
                        'tunnel', '--protocol', 'http2', '--url',
                        'http://127.0.0.1:8765', '--no-autoupdate',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    self.service.tunnel = process
                    self.events.put(('url', ''))
                    self.events.put(('state', ('tunnel', 'Получение ссылки…')))
                    retry_delay = 2
                    self.emit('Запущен Cloudflare Tunnel по HTTP/2. Ожидаю публичный адрес…')
                    import re
                    startup_deadline = asyncio.get_running_loop().time() + 60
                    public_url = None

                    while not self.stop_requested.is_set():
                        if public_url is None:
                            remaining = startup_deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                raise TimeoutError('Cloudflare не выдал публичную ссылку за 60 секунд.')
                            line = await asyncio.wait_for(
                                process.stdout.readline(), timeout=remaining
                            )
                        else:
                            line = await process.stdout.readline()
                        if not line:
                            break
                        decoded = line.decode(errors='replace').strip()
                        # Cloudflared may decorate console output with ANSI colors.
                        decoded = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', decoded)
                        if decoded:
                            self.emit(decoded)
                        if public_url is None:
                            match = re.search(
                                r'https://[a-z0-9-]+\.trycloudflare\.com',
                                decoded,
                                flags=re.IGNORECASE,
                            )
                            if match:
                                public_url = match.group(0).rstrip('.,);]')
                                self.events.put(('url', public_url))
                                self.events.put(('state', ('tunnel', 'Ссылка получена')))
                                self.emit(
                                    'Публичная ссылка получена. Она действует, пока работает этот Tunnel; '
                                    'при переподключении адрес может измениться.'
                                )

                    if self.stop_requested.is_set():
                        break
                    exit_code = await process.wait()
                    self.emit(
                        f'Cloudflare Tunnel завершился (код {exit_code}). '
                        'Discord и локальный сервер остаются запущены; переподключаю туннель.'
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as tunnel_error:
                    if self.stop_requested.is_set():
                        break
                    self.emit(
                        f'Ошибка Cloudflare Tunnel: {type(tunnel_error).__name__}: {tunnel_error}. '
                        'Повторяю подключение.'
                    )
                finally:
                    if process is not None and process.returncode is None:
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            process.kill()
                            await process.wait()
                    if self.service and self.service.tunnel is process:
                        self.service.tunnel = None

                if not self.stop_requested.is_set():
                    self.emit(f'Повторное подключение Cloudflare Tunnel через {retry_delay} сек…')
                    remaining = retry_delay
                    while remaining > 0 and not self.stop_requested.is_set():
                        interval = min(0.25, remaining)
                        await asyncio.sleep(interval)
                        remaining -= interval
                    retry_delay = min(retry_delay * 2, 30)
        except Exception as e:
            self.emit(
                f"Сервис завершился с ошибкой: {type(e).__name__}: {e}. "
                "Передаю управление автоматическому перезапуску."
            )
            raise
        finally:
            if 'status_task' in locals():
                status_task.cancel()
            final_state = 'Остановлен' if self.stop_requested.is_set() else 'Перезапуск…'
            for key in self.service_states:
                self.events.put(('state', (key, final_state)))
            if self.service:
                await self.service.stop()

    async def _watch_service_status(self):
        last_state = None
        while not self.stop_requested.is_set():
            ready = bool(self.service and self.service.ready.is_set())
            value = 'Подключён' if ready else 'Ожидание Discord…'
            if value != last_state:
                self.events.put(('state', ('discord', value)))
                last_state = value
            await asyncio.sleep(1)

    def _apply_system_awake(self, enabled: bool, log: bool = True) -> None:
        """Ask Windows to keep the system awake while allowing the display to sleep."""
        if os.name != 'nt':
            return
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if enabled else ES_CONTINUOUS
        result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
        if result == 0:
            raise ctypes.WinError()
        if log:
            self.emit(
                'Windows: сон системы отключён на время работы бота; экран может выключаться.' if enabled
                else 'Windows: обычный режим энергосбережения восстановлен.'
            )

    def _refresh_system_awake(self) -> None:
        self._keep_awake_job = None
        if not self.keep_awake or self.stop_requested.is_set():
            return
        try:
            self._apply_system_awake(True, log=False)
        except Exception as exc:
            self.emit(f'Не удалось обновить запрет сна Windows: {type(exc).__name__}: {exc}')
        self._keep_awake_job = self.root.after(30_000, self._refresh_system_awake)

    def _set_system_awake(self, enabled: bool) -> None:
        self.keep_awake = enabled
        if enabled:
            try:
                self._apply_system_awake(True)
            except Exception as exc:
                self.emit(f'Не удалось отключить сон Windows: {type(exc).__name__}: {exc}')
            if self._keep_awake_job is None:
                self._keep_awake_job = self.root.after(30_000, self._refresh_system_awake)
        else:
            if self._keep_awake_job is not None:
                try:
                    self.root.after_cancel(self._keep_awake_job)
                except tk.TclError:
                    pass
                self._keep_awake_job = None
            try:
                self._apply_system_awake(False)
            except Exception as exc:
                self.emit(f'Не удалось восстановить режим сна Windows: {type(exc).__name__}: {exc}')

    def stop_service(self):
        self.stop_requested.set()
        if self.keep_awake:
            self._set_system_awake(False)
        if self.service and self.service.tunnel and self.service.tunnel.returncode is None:
            self.service.tunnel.terminate()
        self.status.set('Остановлено')
        for key in self.service_states:
            self.service_states[key].set('Остановлен')
        self.start.configure(text='▶  Запустить бота', command=self.start_service, state='normal')

    def copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.link.get())

    def copy_log(self):
        content = self.log.get('1.0', 'end-1c')
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.root.update_idletasks()

    def copy_selected_log(self):
        try:
            content = self.log.get('sel.first', 'sel.last')
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update_idletasks()

    def clear_log(self):
        self.log.delete('1.0', 'end')

    def protect_log(self, event):
        if event.state & 0x4 and event.keysym.lower() == 'c':
            return None
        if event.state & 0x4 and event.keysym.lower() == 'a':
            return self.select_all_log(event)
        if event.keysym in ('Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Prior', 'Next'):
            return None
        return 'break'

    def select_all_log(self, event=None):
        self.log.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def show_log_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label='Копировать выделенное', command=self.copy_selected_log)
        menu.add_command(label='Выделить всё', command=self.select_all_log)
        menu.add_separator()
        menu.add_command(label='Копировать весь журнал', command=self.copy_log)
        menu.add_command(label='Очистить журнал', command=self.clear_log)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'
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

    from voice_reader.additional_tts import TeraPopTTS
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
        elif engine == "silero_cis":
            tts = LocalSileroTTS(
                VOICE_ASSETS / "v5_cis_base.pt",
                log,
                warmup_speakers=("ru_safarhuja", "ru_eduard", "ru_marat"),
                model_label="Silero v5 CIS Base",
                russian_accentor=True,
            )
            tts.load()
            size, duration = tts.synthesize_to_wav(sample_text, profile["speaker"], output_path)
            del tts
        elif engine == "teratts":
            tts = TeraPopTTS(VOICE_ASSETS / "teratts", log)
            tts.warmup()
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


def run_frozen_ui_smoke_test() -> int:
    """Create the real desktop widgets in the frozen EXE without starting services."""
    root = tk.Tk()
    root.withdraw()
    try:
        app = App(root)
        root.update_idletasks()
        if not app.log.winfo_exists() or app.log.master is not app.log_body:
            raise RuntimeError("Журнал не создан внутри своего контейнера.")
        root.update()
        return 0
    finally:
        root.destroy()


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == '--voice-smoke-test':
        raise SystemExit(run_frozen_voice_smoke_test(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == '--ui-smoke-test':
        raise SystemExit(run_frozen_ui_smoke_test())
    App(tk.Tk()).root.mainloop()
