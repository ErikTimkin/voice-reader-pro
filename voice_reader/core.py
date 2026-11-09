import asyncio
import array
import logging
import math
import os
import queue as thread_queue
import re
import time
from collections import defaultdict, deque
from pathlib import Path

import aiohttp
from aiohttp import web
import discord
import edge_tts
from edge_tts.exceptions import NoAudioReceived

MAX_TEXT, MAX_QUEUE = 350, 20
RATE_WINDOW, RATE_COUNT = 60, 5


class DiagnosticFFmpegPCMAudio(discord.FFmpegPCMAudio):
    """FFmpeg-to-PCM source that reports decoded frame count and signal level."""

    def __init__(self, source, *, executable, logger, pipe=False, before_options=None, options=None):
        self._voice_log = logger
        self._pcm_frames = 0
        self._pcm_bytes = 0
        self._pcm_peak = 0
        self._pcm_sum_squares = 0
        self._pcm_sample_count = 0
        self._pcm_summary_written = False
        super().__init__(
            source,
            executable=executable,
            pipe=pipe,
            before_options=before_options,
            options=options,
        )

    def read(self):
        data = super().read()
        if data:
            self._pcm_frames += 1
            self._pcm_bytes += len(data)
            samples = array.array('h')
            samples.frombytes(data)
            if samples:
                self._pcm_peak = max(self._pcm_peak, max(abs(v) for v in samples))
                self._pcm_sum_squares += sum(v * v for v in samples)
                self._pcm_sample_count += len(samples)
            return data

        if not self._pcm_summary_written:
            self._pcm_summary_written = True
            rms = math.sqrt(self._pcm_sum_squares / self._pcm_sample_count) if self._pcm_sample_count else 0.0
            self._voice_log(
                f'PCM от FFmpeg: кадров={self._pcm_frames}, длительность={self._pcm_frames * 0.02:.2f} сек, '
                f'байт={self._pcm_bytes}, RMS={rms:.1f}, peak={self._pcm_peak}.'
            )
            if self._pcm_frames == 0:
                self._voice_log('ОШИБКА: FFmpeg не выдал ни одного PCM-кадра.')
            elif self._pcm_peak == 0:
                self._voice_log('ОШИБКА: декодированное аудио полностью цифрово-бесшумное.')
            elif rms < 80:
                self._voice_log('ПРЕДУПРЕЖДЕНИЕ: уровень PCM очень низкий; возможна почти полная тишина.')
        return data

class BlockingMP3Stream:
    """File-like blocking reader fed by Edge TTS async audio chunks."""

    def __init__(self):
        self._chunks = thread_queue.Queue()
        self._buffer = bytearray()
        self._finished = False

    def feed(self, data: bytes) -> None:
        if data:
            self._chunks.put(data)

    def finish(self) -> None:
        self._chunks.put(None)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = 8192
        while len(self._buffer) < size and not self._finished:
            chunk = self._chunks.get()
            if chunk is None:
                self._finished = True
                break
            self._buffer.extend(chunk)

        if not self._buffer:
            return b''
        count = min(size, len(self._buffer))
        data = bytes(self._buffer[:count])
        del self._buffer[:count]
        return data


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

        # Forward voice/gateway diagnostics into the GUI journal.
        class UILogHandler(logging.Handler):
            def __init__(self, callback):
                super().__init__(logging.DEBUG)
                self.callback = callback

            def emit(self, record):
                try:
                    self.callback(f'[{record.name} {record.levelname}] {self.format(record)}')
                except Exception:
                    self.handleError(record)

        self._discord_log_handler = UILogHandler(logger)
        self._discord_log_handler.setFormatter(logging.Formatter('%(message)s'))
        for logger_name in ('discord.voice_state', 'discord.voice_client', 'discord.gateway', 'discord.player', 'davey'):
            component_logger = logging.getLogger(logger_name)
            component_logger.setLevel(logging.DEBUG)
            component_logger.addHandler(self._discord_log_handler)
            component_logger.propagate = False

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
        self.log(
            f'Discord voice-state update: {before_name} → {after_name}; '
            f'self_mute={after.self_mute}, self_deaf={after.self_deaf}, '
            f'server_mute={after.mute}, server_deaf={after.deaf}.'
        )
        if after.channel is None:
            self.ready.clear()
            self.log('Discord прислал событие выхода бота из канала. Причину ищите в сообщениях [discord.voice_state] выше.')
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
        request_started = time.perf_counter()
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

        enqueued_at = time.perf_counter()
        await self.queue.put((text, enqueued_at))
        queue_size = self.queue.qsize()
        elapsed_ms = (time.perf_counter() - request_started) * 1000
        self.log(
            f'Сайт → очередь: принято за {elapsed_ms:.0f} мс; '
            f'символов={len(text)}, сообщений впереди={max(0, queue_size - 1)}.'
        )
        return web.json_response({
            'message': 'Принято. Начинаю озвучивание.' if queue_size == 1
            else f'Добавлено в очередь: {queue_size}.'
        })

    async def play_worker(self):
        while True:
            item = await self.queue.get()
            if isinstance(item, tuple):
                text, enqueued_at = item
            else:
                text, enqueued_at = item, time.perf_counter()

            audio_stream = None
            playback_done = None
            voice_client = None
            original_send_audio_packet = None
            playback_started = False

            try:
                queue_wait_ms = (time.perf_counter() - enqueued_at) * 1000
                self.log(f'Начинаю сообщение: очередь ожидала {queue_wait_ms:.0f} мс.')
                if not self.voice_client or not self.voice_client.is_connected():
                    self.ready.clear()
                    self.log('Голосовое соединение потеряно. Новые сообщения временно не принимаются.')
                    continue

                voices_to_try = [self.voice]
                fallback_voice = "ru-RU-SvetlanaNeural"
                if fallback_voice != self.voice:
                    voices_to_try.append(fallback_voice)

                synthesized = False
                last_tts_error = None

                for voice_index, candidate_voice in enumerate(voices_to_try):
                    for attempt in range(1, 3):
                        audio_stream = None
                        playback_done = None
                        playback_started = False
                        voice_client = None
                        original_send_audio_packet = None
                        tts_started = time.perf_counter()

                        try:
                            if voice_index == 0 and attempt == 1:
                                self.log(f'Запрашиваю поток Edge TTS: {candidate_voice}.')
                            elif voice_index == 0:
                                self.log(f'Edge TTS не прислал аудио. Повторная попытка {attempt}/2…')
                            else:
                                self.log(f'Пробую запасной русский голос {candidate_voice}…')

                            communicate = edge_tts.Communicate(text, candidate_voice)
                            audio_bytes = 0

                            async for chunk in communicate.stream():
                                if chunk.get('type') != 'audio':
                                    continue
                                data = chunk.get('data') or b''
                                if not data:
                                    continue

                                audio_bytes += len(data)
                                if not playback_started:
                                    if not self.voice_client or not self.voice_client.is_connected():
                                        self.ready.clear()
                                        raise RuntimeError('Discord voice connection was lost before first audio chunk')

                                    audio_stream = BlockingMP3Stream()
                                    audio_stream.feed(data)
                                    playback_done = asyncio.get_running_loop().create_future()
                                    loop = asyncio.get_running_loop()
                                    voice_client = self.voice_client
                                    connection_state = voice_client._connection
                                    dave_session = getattr(connection_state, 'dave_session', None)
                                    self.log(
                                        'Голосовой тракт: '
                                        f'connected={voice_client.is_connected()}, mode={voice_client.mode}, '
                                        f'DAVE_protocol={getattr(connection_state, "dave_protocol_version", None)}, '
                                        f'DAVE_session_ready={getattr(dave_session, "ready", None)}, '
                                        f'DAVE_can_encrypt={getattr(connection_state, "can_encrypt", None)}, '
                                        f'Opus_loaded={discord.opus.is_loaded()}.'
                                    )

                                    packet_stats = {'count': 0, 'bytes': 0}
                                    original_send_audio_packet = voice_client.send_audio_packet

                                    def counted_send_audio_packet(packet_data, *, encode=True):
                                        original_send_audio_packet(packet_data, encode=encode)
                                        packet_stats['count'] += 1
                                        packet_stats['bytes'] += len(packet_data)

                                    voice_client.send_audio_packet = counted_send_audio_packet

                                    def playback_finished(error):
                                        def finish_on_loop():
                                            voice_client.send_audio_packet = original_send_audio_packet
                                            self.log(
                                                f'Пакеты Discord: {packet_stats["count"]}; '
                                                f'передано данных PCM: {packet_stats["bytes"]} байт.'
                                            )
                                            if error:
                                                self.log(f'Ошибка воспроизведения: {type(error).__name__}: {error!r}')
                                            else:
                                                self.log(
                                                    f'Аудиопоток завершён. Discord подключён: '
                                                    f'{voice_client.is_connected()}.'
                                                )
                                            if not playback_done.done():
                                                playback_done.set_result(error)
                                        try:
                                            loop.call_soon_threadsafe(finish_on_loop)
                                        except RuntimeError:
                                            pass

                                    source = DiagnosticFFmpegPCMAudio(
                                        audio_stream,
                                        executable=self.ffmpeg,
                                        logger=self.log,
                                        pipe=True,
                                        before_options='-nostdin -f mp3',
                                        options='-af volume=1.5',
                                    )
                                    try:
                                        voice_client.play(source, after=playback_finished, signal_type='voice')
                                    except Exception:
                                        voice_client.send_audio_packet = original_send_audio_packet
                                        original_send_audio_packet = None
                                        raise

                                    playback_started = True
                                    first_audio_ms = (time.perf_counter() - tts_started) * 1000
                                    self.log(
                                        f'Первый аудиофрагмент получен за {first_audio_ms:.0f} мс; '
                                        f'начинаю воспроизведение, {len(data)} байт в первом фрагменте.'
                                    )
                                else:
                                    audio_stream.feed(data)

                            if not playback_started:
                                raise NoAudioReceived('Edge TTS finished without returning audio.')

                            audio_stream.finish()
                            total_tts_ms = (time.perf_counter() - tts_started) * 1000
                            self.log(
                                f'Edge TTS передал весь текст за {total_tts_ms:.0f} мс; '
                                f'аудио={audio_bytes} байт, голос={candidate_voice}.'
                            )
                            playback_error = await playback_done
                            if playback_error:
                                self.log(
                                    f'Ошибка передачи звука: {type(playback_error).__name__}: {playback_error!r}'
                                )
                            synthesized = True
                            break

                        except NoAudioReceived as exc:
                            last_tts_error = exc
                            if playback_started and audio_stream is not None:
                                audio_stream.finish()
                                self.log(
                                    f'Edge TTS оборвал поток после начала воспроизведения: {exc}. '
                                    'Уже полученная часть будет доиграна.'
                                )
                                if playback_done is not None:
                                    await playback_done
                                synthesized = True
                                break
                            self.log(
                                f'Edge TTS не вернул первый фрагмент ({candidate_voice}, '
                                f'попытка {attempt}/2): {exc}'
                            )
                            if attempt < 2:
                                await asyncio.sleep(0.8)
                        except Exception as exc:
                            last_tts_error = exc
                            if playback_started and audio_stream is not None:
                                audio_stream.finish()
                                self.log(
                                    f'Поток озвучивания прервался после старта: '
                                    f'{type(exc).__name__}: {exc}'
                                )
                                if playback_done is not None:
                                    await playback_done
                                synthesized = True
                                break
                            self.log(
                                f'Ошибка Edge TTS ({candidate_voice}): {type(exc).__name__}: {exc}'
                            )
                            if attempt < 2:
                                await asyncio.sleep(0.8)
                    if synthesized:
                        break

                if not synthesized:
                    self.log(
                        'Не удалось получить аудио ни основным, ни запасным голосом. '
                        f'Последняя ошибка: {type(last_tts_error).__name__ if last_tts_error else "Unknown"}: '
                        f'{last_tts_error}.'
                    )

            except Exception as exc:
                if audio_stream is not None and playback_started:
                    audio_stream.finish()
                    if playback_done is not None:
                        try:
                            await playback_done
                        except Exception:
                            pass
                if voice_client and original_send_audio_packet is not None:
                    voice_client.send_audio_packet = original_send_audio_packet
                self.log(f'Ошибка озвучивания: {type(exc).__name__}: {exc}')
            finally:
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
