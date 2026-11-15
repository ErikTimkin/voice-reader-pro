"""Low-latency microphone processing for the optional live voice mode.

Audio is routed to a selected playback endpoint. With VB-CABLE installed,
select "CABLE Input" here and "CABLE Output" as the Discord microphone.
"""
from __future__ import annotations

import threading
from typing import Any

SAMPLE_RATE = 48_000
BLOCK_SIZE = 960  # 20 ms at 48 kHz; the DSP also accepts variable block sizes.

PRESETS: dict[str, dict[str, Any]] = {
    "Обычный": {"pitch": 0.0, "bass": 0.0, "treble": 0.0, "drive": 0.0, "radio": False},
    "Низкий": {"pitch": -4.0, "bass": 3.0, "treble": -1.0, "drive": 0.0, "radio": False},
    "Высокий": {"pitch": 4.0, "bass": -1.0, "treble": 2.0, "drive": 0.0, "radio": False},
    "Радио": {"pitch": 0.0, "bass": -2.0, "treble": -2.0, "drive": 3.0, "radio": True},
    "Робот": {"pitch": 0.0, "bass": -1.0, "treble": 1.0, "drive": 18.0, "radio": False},
    "Демон": {"pitch": -7.0, "bass": 5.0, "treble": -3.0, "drive": 8.0, "radio": False},
}


class GranularPitchShifter:
    """Stateful two-head pitch shifter designed for continuous microphone audio.

    It intentionally does not use Pedalboard.PitchShift: its streaming
    reset=False path can return empty/silent buffers in affected releases.
    """

    def __init__(self, sample_rate: int, semitones: float, max_delay_ms: float = 120.0):
        import numpy as np

        self._np = np
        self.ratio = 2.0 ** (float(semitones) / 12.0)
        self.buffer_size = max(int(int(sample_rate) * max_delay_ms / 1000.0), 1024)
        if self.buffer_size % 2:
            self.buffer_size += 1
        self.buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.write_pos = 0
        self.read_a = 0.0
        self.read_b = self.buffer_size / 2.0
        self.phase = 0.0
        self.fade_length = self.buffer_size // 2

    def _read_many(self, positions, write_start: int, block_length: int, old_values, local_indices):
        np = self._np
        size = self.buffer_size
        positions = np.mod(positions, size)
        index_a = np.floor(positions).astype(np.int64)
        index_b = (index_a + 1) % size
        fraction = positions - index_a
        value_a = self.buffer[index_a].copy()
        value_b = self.buffer[index_b].copy()

        # Restore the pre-block value for reads that are still in the future.
        # This makes vectorised processing equivalent to interleaved
        # sample-by-sample ring-buffer reads without a Python loop per sample.
        relative_a = (index_a - write_start) % size
        relative_b = (index_b - write_start) % size
        future_a = (relative_a > local_indices) & (relative_a < block_length)
        future_b = (relative_b > local_indices) & (relative_b < block_length)
        if np.any(future_a):
            value_a[future_a] = old_values[relative_a[future_a]]
        if np.any(future_b):
            value_b[future_b] = old_values[relative_b[future_b]]
        return (1.0 - fraction) * value_a + fraction * value_b

    def _read_one(self, position: float) -> float:
        position %= self.buffer_size
        index_a = int(position)
        index_b = (index_a + 1) % self.buffer_size
        fraction = position - index_a
        return float((1.0 - fraction) * self.buffer[index_a] + fraction * self.buffer[index_b])

    def prime(self, history) -> None:
        """Seed the delay line from recent raw microphone samples during effect changes."""
        np = self._np
        samples = np.ascontiguousarray(history, dtype=np.float32).reshape(-1)
        self.buffer.fill(0.0)
        if samples.size:
            samples = samples[-self.buffer_size:]
            self.buffer[-samples.size:] = samples
        # The next input sample is written at index 0; the buffer tail holds
        # the most recent history so switching presets does not restart silent.
        self.write_pos = 0
        self.read_a = (self.write_pos - self.fade_length) % self.buffer_size
        self.read_b = float(self.write_pos)
        self.phase = 0.0

    def process_block(self, audio):
        """Process a mono float32 chunk; input chunk length may change per call."""
        np = self._np
        source = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        if source.size == 0:
            return source.copy()

        output = np.empty_like(source)
        offset = 0
        size = self.buffer_size
        ratio = self.ratio
        fade_length = self.fade_length

        while offset < source.size:
            steps_to_boundary = max(
                1, int(np.ceil((1.0 - self.phase) * fade_length - 1e-10))
            )
            chunk_size = min(source.size - offset, max(0, steps_to_boundary - 1))

            if chunk_size:
                local = np.arange(chunk_size, dtype=np.int64)
                write_start = self.write_pos
                write_indices = (write_start + local) % size
                old_values = self.buffer[write_indices].copy()
                self.buffer[write_indices] = source[offset:offset + chunk_size]

                read_steps = np.arange(1, chunk_size + 1, dtype=np.float64)
                samples_a = self._read_many(
                    self.read_a + ratio * read_steps, write_start, chunk_size, old_values, local
                )
                samples_b = self._read_many(
                    self.read_b + ratio * read_steps, write_start, chunk_size, old_values, local
                )
                phases = self.phase + read_steps / fade_length
                output[offset:offset + chunk_size] = (
                    np.cos(phases * (np.pi / 2.0)) * samples_a
                    + np.sin(phases * (np.pi / 2.0)) * samples_b
                )

                self.read_a = (self.read_a + ratio * chunk_size) % size
                self.read_b = (self.read_b + ratio * chunk_size) % size
                self.write_pos = (self.write_pos + chunk_size) % size
                self.phase += chunk_size / fade_length
                offset += chunk_size

            # Process a crossfade boundary in the exact streaming sample order.
            if offset < source.size:
                self.buffer[self.write_pos] = source[offset]
                self.write_pos = (self.write_pos + 1) % size
                self.phase += 1.0 / fade_length
                if self.phase >= 1.0 - 1e-10:
                    self.phase -= 1.0
                    self.read_a = self.read_b
                    self.read_b = (self.write_pos - fade_length) % size

                self.read_a = (self.read_a + ratio) % size
                self.read_b = (self.read_b + ratio) % size
                sample_a = self._read_one(self.read_a)
                sample_b = self._read_one(self.read_b)
                output[offset] = (
                    np.cos(self.phase * (np.pi / 2.0)) * sample_a
                    + np.sin(self.phase * (np.pi / 2.0)) * sample_b
                )
                offset += 1

        return np.clip(output, -1.0, 1.0)


def _audio_libraries():
    try:
        import numpy as np
        import sounddevice as sd
        from pedalboard import (
            Compressor,
            Distortion,
            HighpassFilter,
            HighShelfFilter,
            LowpassFilter,
            LowShelfFilter,
            Pedalboard,
        )
    except Exception as exc:
        raise RuntimeError(
            "Не удалось загрузить аудиодвижок. Проверьте установку Voice Reader Pro."
        ) from exc
    return np, sd, {
        "Compressor": Compressor,
        "Distortion": Distortion,
        "HighpassFilter": HighpassFilter,
        "HighShelfFilter": HighShelfFilter,
        "LowpassFilter": LowpassFilter,
        "LowShelfFilter": LowShelfFilter,
        "Pedalboard": Pedalboard,
    }


def list_audio_devices() -> list[dict[str, Any]]:
    """Return audio devices without making assumptions about device names."""
    _, sd, _ = _audio_libraries()
    devices = []
    for index, device in enumerate(sd.query_devices()):
        inputs = int(device.get("max_input_channels", 0))
        outputs = int(device.get("max_output_channels", 0))
        if inputs or outputs:
            devices.append({
                "index": index,
                "name": str(device.get("name", f"Audio device {index}")),
                "inputs": inputs,
                "outputs": outputs,
                "default_samplerate": float(device.get("default_samplerate", SAMPLE_RATE)),
            })
    return devices


class LiveVoiceEngine:
    """Full-duplex microphone processor; output can be routed to VB-CABLE."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream = None
        self._board = None
        self._pitch_shifter = None
        self._np = None
        self._sample_rate = SAMPLE_RATE
        self._history_capacity = max(int(SAMPLE_RATE * 0.12), 1024)
        self._input_history = np.zeros(self._history_capacity, dtype=np.float32)
        self._history_write = 0
        self._history_count = 0
        self._settings = dict(PRESETS["Обычный"])
        self._preset = "Обычный"
        self.last_error: str | None = None
        self.last_status: str = ""

    @property
    def running(self) -> bool:
        return self._stream is not None and bool(getattr(self._stream, "active", False))

    @property
    def preset(self) -> str:
        return self._preset

    def _make_board(self, settings: dict[str, Any]):
        _, _, classes = _audio_libraries()
        plugins = []
        bass = float(settings.get("bass", 0.0))
        treble = float(settings.get("treble", 0.0))
        drive = max(0.0, min(30.0, float(settings.get("drive", 0.0))))

        if settings.get("radio"):
            plugins.extend((
                classes["HighpassFilter"](cutoff_frequency_hz=320.0),
                classes["LowpassFilter"](cutoff_frequency_hz=3_400.0),
            ))
        if abs(bass) >= 0.1:
            plugins.append(classes["LowShelfFilter"](
                cutoff_frequency_hz=140.0, gain_db=max(-12.0, min(12.0, bass))
            ))
        if abs(treble) >= 0.1:
            plugins.append(classes["HighShelfFilter"](
                cutoff_frequency_hz=4_000.0, gain_db=max(-12.0, min(12.0, treble))
            ))
        if drive > 0:
            plugins.append(classes["Distortion"](drive_db=drive))
        plugins.append(classes["Compressor"](threshold_db=-18.0, ratio=2.5))
        return classes["Pedalboard"](plugins)

    @staticmethod
    def _make_pitch_shifter(settings: dict[str, Any], sample_rate: int):
        semitones = float(settings.get("pitch", 0.0))
        return GranularPitchShifter(sample_rate, semitones) if abs(semitones) >= 0.1 else None

    def _history_snapshot_locked(self):
        if self._history_count <= 0:
            return self._input_history[:0].copy()
        start = (self._history_write - self._history_count) % self._history_capacity
        indices = (start + self._np.arange(self._history_count)) % self._history_capacity
        return self._input_history[indices].copy()

    def _remember_input_locked(self, samples) -> None:
        count = int(samples.size)
        if count >= self._history_capacity:
            self._input_history[:] = samples[-self._history_capacity:]
            self._history_write = 0
            self._history_count = self._history_capacity
            return
        indices = (self._history_write + self._np.arange(count)) % self._history_capacity
        self._input_history[indices] = samples
        self._history_write = (self._history_write + count) % self._history_capacity
        self._history_count = min(self._history_capacity, self._history_count + count)

    def configure(self, preset: str, settings: dict[str, Any] | None = None) -> None:
        if preset not in PRESETS:
            raise ValueError(f"Неизвестный пресет: {preset}")
        next_settings = dict(PRESETS[preset])
        if settings:
            for key in ("pitch", "bass", "treble", "drive"):
                if key in settings:
                    next_settings[key] = float(settings[key])
        next_board = self._make_board(next_settings)
        next_pitch_shifter = self._make_pitch_shifter(next_settings, self._sample_rate)
        with self._lock:
            if next_pitch_shifter is not None:
                next_pitch_shifter.prime(self._history_snapshot_locked())
            self._settings = next_settings
            self._preset = preset
            self._board = next_board
            self._pitch_shifter = next_pitch_shifter

    def start(self, input_device: int, output_device: int) -> None:
        if self.running:
            return
        np, sd, _ = _audio_libraries()
        self._np = np
        self.last_error = None
        self.last_status = ""
        if self._board is None:
            self.configure(self._preset, self._settings)

        selected_rate = SAMPLE_RATE
        try:
            sd.check_input_settings(device=input_device, channels=1, dtype="float32", samplerate=selected_rate)
            sd.check_output_settings(device=output_device, channels=1, dtype="float32", samplerate=selected_rate)
        except Exception:
            selected_rate = 44_100
            sd.check_input_settings(device=input_device, channels=1, dtype="float32", samplerate=selected_rate)
            sd.check_output_settings(device=output_device, channels=1, dtype="float32", samplerate=selected_rate)

        with self._lock:
            if selected_rate != self._sample_rate:
                self._sample_rate = selected_rate
                self._history_capacity = max(int(selected_rate * 0.12), 1024)
                self._input_history = np.zeros(self._history_capacity, dtype=np.float32)
                self._history_write = 0
                self._history_count = 0
                self._pitch_shifter = self._make_pitch_shifter(self._settings, selected_rate)

        stream = sd.Stream(
            device=(int(input_device), int(output_device)),
            samplerate=selected_rate,
            blocksize=BLOCK_SIZE,
            channels=(1, 1),
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def process_block(self, audio):
        """Process one mono float32 block; exposed for deterministic DSP tests."""
        np = self._np
        if np is None:
            np, _, _ = _audio_libraries()
        samples = np.asarray(audio, dtype="float32").reshape(-1)
        with self._lock:
            board = self._board
            pitch_shifter = self._pitch_shifter
            self._remember_input_locked(samples)
        if board is None:
            self.configure(self._preset, self._settings)
            with self._lock:
                board = self._board
                pitch_shifter = self._pitch_shifter
        if pitch_shifter is not None:
            samples = pitch_shifter.process_block(samples)
        processed = board(samples.reshape(1, -1), self._sample_rate, reset=False)
        processed = np.asarray(processed, dtype="float32").reshape(-1)
        if processed.size != samples.size:
            if processed.size > samples.size:
                processed = processed[:samples.size]
            else:
                processed = np.pad(processed, (0, samples.size - processed.size))
        return np.clip(processed, -1.0, 1.0)

    def _callback(self, indata, outdata, frames, time_info, status) -> None:
        if status:
            self.last_status = str(status)
        try:
            outdata[:, 0] = self.process_block(indata[:, 0])
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            outdata.fill(0)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                if stream.active:
                    stream.stop()
            finally:
                stream.close()

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._board = None
            self._pitch_shifter = None
            self._np = None
