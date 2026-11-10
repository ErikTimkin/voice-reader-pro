import asyncio
import array
import logging
import math
import os
import queue
import re
import threading
import tempfile
import time
from pathlib import Path

import aiohttp
from aiohttp import web
import discord
from voice_reader.voice_profiles import (VOICE_PRESETS, LEGACY_VOICE_IDS, resolve_voice_profile)
from voice_reader.local_tts import LocalSileroTTS
from voice_reader.additional_tts import ArmenianAccentTTS, TeraPopTTS
from voice_reader.number_normalizer import normalize_numbers_for_speech

MAX_TEXT = 350


def normalize_voice_key(value, default="normal"):
    raw_key = str(value if value is not None else default).strip()
    key = LEGACY_VOICE_IDS.get(raw_key, raw_key)
    if key not in VOICE_PRESETS:
        raise ValueError("Неизвестный голос. Обновите страницу и выберите доступный вариант.")
    return key

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


class StreamingPCMSource(discord.AudioSource):
    """Thread-safe 48 kHz stereo PCM source fed by Pocket TTS chunks."""

    FRAME_BYTES = 3840  # 20 ms, 48 kHz, 16-bit, stereo

    def __init__(self, logger):
        self.log = logger
        self._frames = queue.Queue(maxsize=150)
        self.stop_event = threading.Event()
        self._finished = False
        self._error = None
        self._bytes = 0
        self._frames_read = 0

    def push_mono_24k(self, samples):
        import numpy as np
        if self.stop_event.is_set():
            return
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size < 2:
            return
        # Linear 2x resampling is sufficient for voice-band PCM and avoids
        # adding a heavy audio dependency to the offline Windows package.
        source_x = np.arange(samples.size, dtype=np.float32)
        target_x = np.arange(samples.size * 2, dtype=np.float32) * 0.5
        upsampled = np.interp(target_x, source_x, samples).astype(np.float32)
        pcm_mono = (np.clip(upsampled, -1.0, 1.0) * 32767.0).astype(np.int16)
        stereo = np.repeat(pcm_mono, 2)
        payload = stereo.tobytes()
        for offset in range(0, len(payload), self.FRAME_BYTES):
            if self.stop_event.is_set():
                return
            frame = payload[offset:offset + self.FRAME_BYTES]
            if len(frame) < self.FRAME_BYTES:
                frame += bytes(self.FRAME_BYTES - len(frame))
            while not self.stop_event.is_set():
                try:
                    self._frames.put(frame, timeout=0.1)
                    self._bytes += len(frame)
                    break
                except queue.Full:
                    continue

    def finish(self, error=None):
        if self._finished:
            return
        self._finished = True
        self._error = error
        if self.stop_event.is_set():
            # A stopped Discord player no longer drains the queue.
            while True:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    break
        self._frames.put(None)

    def read(self):
        frame = self._frames.get()
        if frame is None:
            return b""
        self._frames_read += 1
        return frame

    def is_opus(self):
        return False

    def cleanup(self):
        self.stop_event.set()
        if not self._finished:
            self.finish()


class VoiceService:
    def __init__(self, token, guild_id, channel_id, voice, ffmpeg, logger, tts_model_path):
        self.token = token
        self.guild_id, self.channel_id = int(guild_id), int(channel_id)
        self.voice, self.ffmpeg, self.log = voice, str(ffmpeg), logger
        self.local_tts = LocalSileroTTS(tts_model_path, logger)
        voice_assets = Path(tts_model_path).parent
        self.armenian_tts = ArmenianAccentTTS(voice_assets / "armenian", logger)
        self.pop_tts = TeraPopTTS(voice_assets / "teratts", logger)
        self.tts_ready = asyncio.Event()
        self.tts_error = None
        self.armenian_ready = asyncio.Event()
        self.armenian_error = None
        # Unbounded FIFO: users can submit repeatedly without per-minute throttling.
        self.queue = asyncio.Queue()
        self.client = discord.Client(intents=discord.Intents(guilds=True, voice_states=True))
        self.runner = self.site = self.tunnel = self.worker = self.discord_task = self.start_watchdog = None
        self.tts_load_task = self.loop_watchdog_task = self.voice_watchdog_task = None
        self.voice_client = None
        self.ready = asyncio.Event()

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
        app.router.add_get('/api/status', self.status)
        app.router.add_post('/api/speak', self.speak)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 8765)
        await self.site.start()
        self.worker = asyncio.create_task(self.play_worker())
        self.tts_load_task = asyncio.create_task(self._load_local_tts())
        self.armenian_load_task = asyncio.create_task(self._preload_armenian_tts())
        self.loop_watchdog_task = asyncio.create_task(self._watch_event_loop())
        self.voice_watchdog_task = asyncio.create_task(self._watch_voice_connection())
        self.discord_task = asyncio.create_task(self._start_discord())
        self.discord_task.add_done_callback(self._discord_finished)
        self.start_watchdog = asyncio.create_task(self._check_discord_startup())
        self.log('Веб-сервер запущен. Загружается обычный мужской и женский голос; подключаем бота к Discord…')

    async def _load_local_tts(self):
        started = time.perf_counter()
        try:
            # CPU-heavy model loading and warm-up must not block Discord heartbeats.
            await asyncio.to_thread(self.local_tts.load)
            elapsed = (time.perf_counter() - started) * 1000
            self.log(f'Локальная модель Silero готова за {elapsed:.0f} мс. Обычный и женский голоса доступны.')
        except Exception as exc:
            self.tts_error = f'{type(exc).__name__}: {exc}'
            self.log(f'Не удалось загрузить локальную модель голоса: {self.tts_error}')
        finally:
            self.tts_ready.set()

    async def _preload_armenian_tts(self):
        """Load the Armenian-accent model before its first request, off the Discord loop."""
        try:
            # Pocket TTS is an independent engine: never wait for Silero and
            # never skip Armenian initialization because Silero failed.
            # Keep the short delay only to let Discord finish connecting.
            await asyncio.sleep(2)
            started = time.perf_counter()
            await asyncio.to_thread(self.armenian_tts.load)
            elapsed = (time.perf_counter() - started) * 1000
            self.log(
                f"Армянская модель заранее загружена за {elapsed:.0f} мс. "
                "Первое сообщение не будет ждать загрузку весов и подготовку тембра."
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep the other voices available if this optional model fails to load.
            self.armenian_error = f"{type(exc).__name__}: {exc}"
            self.log(f"Не удалось заранее загрузить армянский голос: {self.armenian_error}")
        finally:
            self.armenian_ready.set()

    async def _watch_event_loop(self):
        # Discord heartbeat warnings mean the asyncio loop was not scheduled.
        loop = asyncio.get_running_loop()
        expected = loop.time() + 1.0
        while True:
            await asyncio.sleep(1.0)
            now = loop.time()
            lag = now - expected
            if lag > 0.75:
                self.log(f'Задержка event loop: {lag:.2f} сек. Синтез голоса выполняется в отдельном потоке.')
            expected = now + 1.0

    async def _watch_voice_connection(self):
        """Recover the configured voice connection after transient Discord drops."""
        while True:
            await asyncio.sleep(15)
            if not self.client.is_ready():
                continue
            current = self.voice_client
            if current and current.is_connected():
                continue
            self.ready.clear()
            self.log('Проверка соединения: бот не в голосовом канале. Пробую восстановить подключение…')
            try:
                await self.on_ready()
            except Exception as exc:
                self.log(f'Не удалось автоматически восстановить голосовое соединение: {type(exc).__name__}: {exc}')

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
        page_path = Path(__file__).parent / 'static' / 'index.html'
        page = page_path.read_text(encoding='utf-8')
        default_voice = self.voice if self.voice in VOICE_PRESETS else 'normal'
        page = page.replace('__DEFAULT_VOICE__', default_voice)
        return web.Response(
            text=page,
            content_type='text/html',
            charset='utf-8',
            headers={'Cache-Control': 'no-store'},
        )

    async def status(self, request):
        voice_client = self.voice_client
        connected = bool(voice_client and voice_client.is_connected())
        dave_ready = None
        if connected:
            state = voice_client._connection
            dave_ready = getattr(state, 'can_encrypt', None)
        return web.json_response({
            'connected': connected,
            'ready': bool(self.ready.is_set() and connected),
            'dave_ready': dave_ready,
            'queue_size': self.queue.qsize(),
        })

    async def speak(self, request):
        request_started = time.perf_counter()
        if not self.ready.is_set():
            return web.json_response({'message': 'Бот ещё не подключён к голосовому каналу.'}, status=503)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            text = payload.get('text', '')
            requested_voice = normalize_voice_key(payload.get('voice'), self.voice)
        except ValueError as exc:
            return web.json_response({'message': str(exc) or 'Некорректный запрос.'}, status=400)
        except Exception:
            return web.json_response({'message': 'Некорректный запрос.'}, status=400)
        text = re.sub(r'[ \t]+', ' ', str(text))
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        if not text or len(text) > MAX_TEXT:
            return web.json_response({'message': 'Введите от 1 до 350 символов.'}, status=400)
        enqueued_at = time.perf_counter()
        await self.queue.put((text, requested_voice, enqueued_at))
        queue_size = self.queue.qsize()
        elapsed_ms = (time.perf_counter() - request_started) * 1000
        self.log(
            f'Сайт → очередь: принято за {elapsed_ms:.0f} мс; '
            f'символов={len(text)}, сообщений впереди={max(0, queue_size - 1)}.'
        )
        message = 'Принято. Начинаю озвучивание.' if queue_size == 1 else f'Добавлено в очередь: {queue_size}.'
        return web.json_response({'message': message})

    async def play_worker(self):
        while True:
            item = await self.queue.get()
            if isinstance(item, tuple) and len(item) == 3:
                text, selected_voice, enqueued_at = item
            elif isinstance(item, tuple) and len(item) == 2:
                text, enqueued_at = item
                selected_voice = self.voice
            else:
                text, selected_voice, enqueued_at = item, self.voice, time.perf_counter()

            file_name = None
            done = None
            voice_client = None
            original_send_packet = None
            original_get_voice_packet = None

            try:
                queue_wait_ms = (time.perf_counter() - enqueued_at) * 1000
                self.log(f'Начинаю сообщение: очередь ожидала {queue_wait_ms:.0f} мс.')

                if not self.voice_client or not self.voice_client.is_connected():
                    self.ready.clear()
                    self.log('Голосовое соединение потеряно. Новые сообщения временно не принимаются.')
                    continue

                profile = resolve_voice_profile(selected_voice)
                speech_text = normalize_numbers_for_speech(text)
                engine = profile.get("engine", "armenian")

                # Each engine has its own readiness and error state. A failed
                # Silero load must not disable the independent Armenian model.
                if engine == "silero":
                    await self.tts_ready.wait()
                    if self.tts_error:
                        self.log(
                            f'Голос «{profile["label"]}» недоступен: '
                            f'ошибка загрузки Silero: {self.tts_error}'
                        )
                        continue
                elif engine == "armenian":
                    await self.armenian_ready.wait()
                    if self.armenian_error:
                        self.log(
                            f'Голос «{profile["label"]}» недоступен: '
                            f'ошибка загрузки Pocket TTS: {self.armenian_error}'
                        )
                        continue
                self.log(
                    f'Локальная озвучка: {profile["label"]}; '
                    f'движок={engine}; диктор={profile.get("speaker", selected_voice)}.'
                )
                if speech_text != text:
                    self.log(f'Числа преобразованы в слова перед озвучкой: {speech_text[:180]}')

                if engine == "armenian":
                    # Stream chunks directly to Discord; do not synthesize a
                    # second full WAV before playback starts.
                    self.log("Армянский голос: запускаю потоковую генерацию.")
                else:
                    fd, file_name = tempfile.mkstemp(suffix='.wav', prefix='voice-reader-')
                    os.close(fd)
                    synth_started = time.perf_counter()

                    # Neural inference stays off the asyncio loop.
                    if engine == "silero":
                        audio_bytes, audio_duration = await asyncio.to_thread(
                            self.local_tts.synthesize_to_wav,
                            speech_text,
                            profile["speaker"],
                            file_name,
                        )
                    elif engine == "teratts":
                        audio_bytes, audio_duration = await asyncio.to_thread(
                            self.pop_tts.synthesize_to_wav,
                            speech_text,
                            file_name,
                        )
                    else:
                        raise RuntimeError(f"Неизвестный движок озвучивания: {engine}")
                    synth_ms = (time.perf_counter() - synth_started) * 1000
                    self.log(
                        f'Локальная модель создала звук за {synth_ms:.0f} мс: '
                        f'{audio_duration:.2f} сек, {audio_bytes} байт.'
                    )

                if not self.voice_client or not self.voice_client.is_connected():
                    self.ready.clear()
                    self.log('Голосовое соединение оборвалось во время локального синтеза.')
                    continue

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

                done = asyncio.get_running_loop().create_future()
                loop = asyncio.get_running_loop()
                packet_stats = {
                    'opus_frames': 0,
                    'encrypted_packets': 0,
                    'udp_sent': 0,
                    'udp_errors': 0,
                    'dave_dropped': 0,
                    'bytes': 0,
                }
                # Count at the actual UDP socket boundary. Counting calls to
                # send_audio_packet alone is misleading: DAVE may intentionally
                # drop frames before encryption when its session is not ready.
                original_send_packet = connection_state.send_packet
                original_get_voice_packet = voice_client._get_voice_packet

                def counted_get_voice_packet(data):
                    packet_stats['opus_frames'] += 1
                    packet = original_get_voice_packet(data)
                    if packet is None:
                        packet_stats['dave_dropped'] += 1
                    else:
                        packet_stats['encrypted_packets'] += 1
                    return packet

                def counted_udp_send(packet):
                    try:
                        result = original_send_packet(packet)
                    except OSError:
                        packet_stats['udp_errors'] += 1
                        raise
                    packet_stats['udp_sent'] += 1
                    packet_stats['bytes'] += len(packet)
                    return result

                voice_client._get_voice_packet = counted_get_voice_packet
                connection_state.send_packet = counted_udp_send

                def playback_finished(error):
                    def finish_on_loop():
                        voice_client._get_voice_packet = original_get_voice_packet
                        connection_state.send_packet = original_send_packet
                        self.log(
                            'Аудиотракт Discord: '
                            f'Opus-кадров={packet_stats["opus_frames"]}, '
                            f'зашифровано={packet_stats["encrypted_packets"]}, '
                            f'UDP отправлено={packet_stats["udp_sent"]}, '
                            f'UDP ошибок={packet_stats["udp_errors"]}, '
                            f'DAVE отбросил={packet_stats["dave_dropped"]}, '
                            f'байт UDP={packet_stats["bytes"]}.'
                        )
                        if packet_stats['dave_dropped'] and not packet_stats['udp_sent']:
                            self.log(
                                'ОШИБКА: Discord не отправил аудио: DAVE не разрешил шифрование '
                                'пакетов. Голосовая E2EE-сессия не завершила переход ключей.'
                            )
                        elif packet_stats['udp_errors']:
                            self.log('ОШИБКА: UDP-сокет не смог отправить часть аудиопакетов.')
                        elif packet_stats['udp_sent'] == 0:
                            self.log('ОШИБКА: аудиоплеер завершился, но ни одного UDP-пакета не отправлено.')
                        elif packet_stats['udp_sent'] > 0:
                            self.log('UDP-сокет принял аудиопакеты для отправки в Discord.')

                        if error:
                            self.log(f'Ошибка воспроизведения: {type(error).__name__}: {error!r}')
                        else:
                            self.log(
                                f'Локальный аудиофайл передан. Discord подключён: '
                                f'{voice_client.is_connected()}.'
                            )
                        if not done.done():
                            done.set_result(error)
                    try:
                        loop.call_soon_threadsafe(finish_on_loop)
                    except RuntimeError:
                        pass

                if engine == "armenian":
                    source = StreamingPCMSource(self.log)
                    def generate_armenian_stream():
                        try:
                            self.armenian_tts.stream_to_source(speech_text, source)
                        except Exception as stream_error:
                            source.finish(stream_error)
                            self.log(
                                f'Ошибка потокового армянского синтеза: '
                                f'{type(stream_error).__name__}: {stream_error}'
                            )
                    threading.Thread(
                        target=generate_armenian_stream,
                        name="armenian-tts-stream",
                        daemon=True,
                    ).start()
                    self.log('Армянская речь передаётся в Discord по мере генерации.')
                else:
                    source = DiagnosticFFmpegPCMAudio(
                        file_name,
                        executable=self.ffmpeg,
                        logger=self.log,
                        before_options='-nostdin',
                        options=profile.get('ffmpeg_options', ''),
                    )
                try:
                    voice_client.play(source, after=playback_finished, signal_type='voice')
                except Exception:
                    voice_client._get_voice_packet = original_get_voice_packet
                    connection_state.send_packet = original_send_packet
                    original_get_voice_packet = None
                    original_send_packet = None
                    if engine == "armenian":
                        source.cleanup()
                    raise

                playback_error = await done
                if playback_error:
                    self.log(
                        f'Ошибка передачи локального звука: '
                        f'{type(playback_error).__name__}: {playback_error!r}'
                    )

            except Exception as exc:
                if voice_client and original_get_voice_packet is not None:
                    voice_client._get_voice_packet = original_get_voice_packet
                if voice_client and original_send_packet is not None:
                    voice_client._connection.send_packet = original_send_packet
                self.log(f'Ошибка локального озвучивания: {type(exc).__name__}: {exc}')
            finally:
                if file_name:
                    try:
                        Path(file_name).unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        self.log(f'Не удалось удалить временный WAV: {cleanup_error}')
                self.queue.task_done()

    async def stop(self):
        for task in (
            self.worker,
            self.discord_task,
            self.start_watchdog,
            self.tts_load_task,
            self.armenian_load_task,
            self.loop_watchdog_task,
            self.voice_watchdog_task,
        ):
            if task and not task.done():
                task.cancel()
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        if not self.client.is_closed():
            await self.client.close()
        if self.runner:
            await self.runner.cleanup()
