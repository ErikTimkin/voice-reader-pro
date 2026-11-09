import asyncio
import os
import re
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

import aiohttp
from aiohttp import web
import discord
import edge_tts

MAX_TEXT, MAX_QUEUE = 350, 20
RATE_WINDOW, RATE_COUNT = 60, 5

class VoiceService:
    def __init__(self, token, guild_id, channel_id, voice, ffmpeg, logger):
        self.token = token
        self.guild_id, self.channel_id = int(guild_id), int(channel_id)
        self.voice, self.ffmpeg, self.log = voice, str(ffmpeg), logger
        self.queue = asyncio.Queue(MAX_QUEUE)
        self.client = discord.Client(intents=discord.Intents(guilds=True, voice_states=True))
        self.runner = self.site = self.tunnel = self.worker = self.discord_task = self.start_watchdog = None
        self.voice_client = None
        self.ready = asyncio.Event()
        self.visitors = defaultdict(deque)
        self.client.event(self.on_ready)
        self.client.event(self.on_voice_state_update)
        self.client.event(self.on_disconnect)
        self.client.event(self.on_resumed)

    async def on_ready(self):
        # on_ready may fire again after a Discord gateway reconnect.
        # Serialize attempts and reuse a healthy existing voice connection.
        if not hasattr(self, '_voice_connect_lock'):
            self._voice_connect_lock = asyncio.Lock()
        async with self._voice_connect_lock:
            guild = self.client.get_guild(self.guild_id)
            if guild is None:
                self.ready.clear()
                self.log('Discord авторизовал бота, но нужный сервер не найден в кеше. Проверьте ID сервера и приглашение.')
                return
            channel = guild.get_channel(self.channel_id)
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                self.ready.clear()
                self.log('Сервер найден, но указанный ID не является доступным голосовым каналом.')
                return
            try:
                current = guild.voice_client
                if current and current.is_connected():
                    if current.channel and current.channel.id != channel.id:
                        self.log(f'Бот уже в канале «{current.channel.name}», перемещаю в «{channel.name}».')
                        await current.move_to(channel)
                    self.voice_client = current
                    self.ready.set()
                    self.log(f'Голосовое соединение активно: «{channel.name}».')
                    return
                if current:
                    self.log('Обнаружено старое отключённое голосовое соединение. Очищаю его перед повторным входом.')
                    try:
                        await current.disconnect(force=True)
                    except Exception as cleanup_error:
                        self.log(f'Не удалось очистить старое соединение: {cleanup_error}')
                self.ready.clear()
                self.log(f'Пробую подключиться к голосовому каналу «{channel.name}»…')
                self.voice_client = await channel.connect(reconnect=True, timeout=30)
                if not self.voice_client.is_connected():
                    raise RuntimeError('Discord создал голосовой клиент, но соединение не установлено.')
                self.ready.set()
                self.log(f'Бот успешно подключился к голосовому каналу «{channel.name}».')
            except Exception as exc:
                self.ready.clear()
                self.log(f'Ошибка голосового подключения: {type(exc).__name__}: {exc}')
                self.voice_client = guild.voice_client

    async def on_voice_state_update(self, member, before, after):
        if self.client.user is None or member.id != self.client.user.id:
            return
        before_name = before.channel.name if before.channel else 'вне канала'
        after_name = after.channel.name if after.channel else 'вне канала'
        self.log(f'Discord изменил голосовое состояние бота: {before_name} → {after_name}.')
        if after.channel is None:
            self.ready.clear()
        elif after.channel.id == self.channel_id:
            self.ready.set()

    async def on_disconnect(self):
        self.ready.clear()
        self.log('Потеряно соединение бота с Discord Gateway. Клиент пытается восстановить связь…')

    async def on_resumed(self):
        self.log('Соединение с Discord Gateway восстановлено.')

    async def start(self):
        app = web.Application(client_max_size=2048)
        app.router.add_get('/', self.index)
        app.router.add_post('/api/speak', self.speak)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 8765)
        await self.site.start()
        self.worker = asyncio.create_task(self.play_worker())
        self.discord_task = asyncio.create_task(self._start_discord())
        self.discord_task.add_done_callback(self._discord_finished)
        self.start_watchdog = asyncio.create_task(self._check_discord_startup())
        self.log('Веб-сервер запущен. Подключаем бота к Discord…')

    async def _start_discord(self):
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            headers = {'Authorization': f'Bot {self.token}'}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get('https://discord.com/api/v10/users/@me', headers=headers) as response:
                    if response.status == 401:
                        self.log('Discord отклонил токен (401). Проверьте Bot Token в Developer Portal → Bot.')
                        return
                    if response.status == 403:
                        self.log('Discord запретил доступ к API (403). Проверьте сеть/VPN.')
                        return
                    if response.status != 200:
                        body = (await response.text())[:200]
                        self.log(f'Discord API вернул {response.status}: {body}')
                        return
                    bot_info = await response.json()
                    self.log(f'Токен принят. Бот: {bot_info.get("username", "без имени")}. Запускаем gateway…')
            await self.client.start(self.token)
        except asyncio.TimeoutError:
            self.log('Тайм-аут при обращении к Discord. Проверьте VPN, прокси или брандмауэр.')
        except aiohttp.ClientError as exc:
            self.log(f'Сетевая ошибка Discord: {type(exc).__name__}: {exc}')
        except discord.LoginFailure:
            self.log('Discord отклонил токен бота. Создайте новый Bot Token и вставьте его в программу.')
        except Exception as exc:
            self.log(f'Ошибка запуска Discord: {type(exc).__name__}: {exc}')

    async def _check_discord_startup(self):
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            self.log('За 30 секунд бот не подключился к голосовому каналу. Смотрите предыдущие сообщения журнала.')

    def _discord_finished(self, task):
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:
            self.log(f'Соединение Discord завершилось с ошибкой: {type(exc).__name__}: {exc}')

    async def index(self, request):
        return web.FileResponse(Path(__file__).parent / 'static' / 'index.html')

    def allowed(self, request):
        ip = request.remote or 'unknown'
        now = time.monotonic()
        bucket = self.visitors[ip]
        while bucket and now - bucket[0] > RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= RATE_COUNT:
            return False
        bucket.append(now)
        return True

    async def speak(self, request):
        if not self.ready.is_set():
            return web.json_response({'message': 'Бот ещё не подключён к голосовому каналу.'}, status=503)
        if not self.allowed(request):
            return web.json_response({'message': 'Слишком много сообщений. Подождите минуту.'}, status=429)
        try:
            payload = await request.json()
            text = payload.get('text', '')
        except Exception:
            return web.json_response({'message': 'Некорректный запрос.'}, status=400)
        text = re.sub(r'\s+', ' ', str(text)).strip()
        if not text or len(text) > MAX_TEXT:
            return web.json_response({'message': 'Введите от 1 до 350 символов.'}, status=400)
        if self.queue.full():
            return web.json_response({'message': 'Очередь заполнена. Попробуйте позже.'}, status=429)
        await self.queue.put(text)
        return web.json_response({'message': f'Добавлено в очередь: {self.queue.qsize()}.'})

    async def play_worker(self):
        while True:
            text = await self.queue.get()
            file_name = None
            try:
                if not self.voice_client or not self.voice_client.is_connected():
                    self.ready.clear()
                    self.log('Голосовое соединение потеряно. Новые сообщения временно не принимаются.')
                    continue
                fd, file_name = tempfile.mkstemp(suffix='.mp3')
                os.close(fd)
                await edge_tts.Communicate(text, self.voice).save(file_name)
                done = asyncio.get_running_loop().create_future()
                loop = asyncio.get_running_loop()
                self.voice_client.play(
                    discord.FFmpegOpusAudio(file_name, executable=self.ffmpeg),
                    after=lambda err: loop.call_soon_threadsafe(
                        lambda: (not done.done()) and done.set_result(err)
                    )
                )
                err = await done
                if err:
                    self.log(f'Ошибка воспроизведения: {err}')
            except Exception as exc:
                self.log(f'Ошибка озвучивания: {type(exc).__name__}: {exc}')
            finally:
                if file_name:
                    Path(file_name).unlink(missing_ok=True)
                self.queue.task_done()

    async def stop(self):
        if self.worker:
            self.worker.cancel()
        if self.discord_task and not self.discord_task.done():
            self.discord_task.cancel()
        if self.start_watchdog and not self.start_watchdog.done():
            self.start_watchdog.cancel()
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        if not self.client.is_closed():
            await self.client.close()
        if self.runner:
            await self.runner.cleanup()
