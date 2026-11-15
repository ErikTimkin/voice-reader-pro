"""Low-latency microphone processing for the optional live voice mode.

The engine writes processed microphone audio to a selected Windows playback
endpoint. With VB-CABLE installed, choose "CABLE Input" here; Windows exposes
the paired "CABLE Output" endpoint as a recording device for Discord and games.
"""
from __future__ import annotations

import threading
from typing import Any

SAMPLE_RATE = 48_000
BLOCK_SIZE = 960  # 20 ms at 48 kHz; a stability-first starting point.

PRESETS: dict[str, dict[str, Any]] = {
    "Обычный": {"pitch": 0.0, "bass": 0.0, "treble": 0.0, "drive": 0.0, "radio": False},
    "Низкий": {"pitch": -4.0, "bass": 3.0, "treble": -1.0, "drive": 0.0, "radio": False},
    "Высокий": {"pitch": 4.0, "bass": -1.0, "treble": 2.0, "drive": 0.0, "radio": False},
    "Радио": {"pitch": 0.0, "bass": -2.0, "treble": -2.0, "drive": 3.0, "radio": True},
    "Робот": {"pitch": 0.0, "bass": -1.0, "treble": 1.0, "drive": 18.0, "radio": False},
    "Демон": {"pitch": -7.0, "bass": 5.0, "treble": -3.0, "drive": 8.0, "radio": False},
}


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
            PitchShift,
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
        "PitchShift": PitchShift,
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
        self._np = None
        self._sample_rate = SAMPLE_RATE
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
        pitch = float(settings.get("pitch", 0.0))
        bass = float(settings.get("bass", 0.0))
        treble = float(settings.get("treble", 0.0))
        drive = max(0.0, min(30.0, float(settings.get("drive", 0.0))))

        if abs(pitch) >= 0.1:
            plugins.append(classes["PitchShift"](semitones=pitch))
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

    def configure(self, preset: str, settings: dict[str, Any] | None = None) -> None:
        if preset not in PRESETS:
            raise ValueError(f"Неизвестный пресет: {preset}")
        next_settings = dict(PRESETS[preset])
        if settings:
            for key in ("pitch", "bass", "treble", "drive"):
                if key in settings:
                    next_settings[key] = float(settings[key])
        next_board = self._make_board(next_settings)
        with self._lock:
            self._settings = next_settings
            self._preset = preset
            self._board = next_board

    def start(self, input_device: int, output_device: int) -> None:
        if self.running:
            return
        np, sd, _ = _audio_libraries()
        self._np = np
        self.last_error = None
        self.last_status = ""
        if self._board is None:
            self.configure(self._preset, self._settings)

        # Validate both endpoints before opening the stream, and try a common
        # fallback rate if a particular driver does not support 48 kHz.
        selected_rate = SAMPLE_RATE
        try:
            sd.check_input_settings(device=input_device, channels=1, dtype="float32", samplerate=selected_rate)
            sd.check_output_settings(device=output_device, channels=1, dtype="float32", samplerate=selected_rate)
        except Exception:
            selected_rate = 44_100
            sd.check_input_settings(device=input_device, channels=1, dtype="float32", samplerate=selected_rate)
            sd.check_output_settings(device=output_device, channels=1, dtype="float32", samplerate=selected_rate)

        self._sample_rate = selected_rate
        stream = sd.Stream(
            device=(int(input_device), int(output_device)),
            samplerate=selected_rate,
            blocksize=max(1, round(BLOCK_SIZE * selected_rate / SAMPLE_RATE)),
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
        with self._lock:
            board = self._board
        if board is None:
            self.configure(self._preset, self._settings)
            with self._lock:
                board = self._board
        samples = np.asarray(audio, dtype="float32").reshape(1, -1)
        processed = board(samples, self._sample_rate, reset=False)
        processed = np.asarray(processed, dtype="float32").reshape(-1)
        if processed.size != samples.shape[1]:
            if processed.size > samples.shape[1]:
                processed = processed[:samples.shape[1]]
            else:
                processed = np.pad(processed, (0, samples.shape[1] - processed.size))
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
            self._np = None
