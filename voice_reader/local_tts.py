from __future__ import annotations

import os
import wave
from pathlib import Path
from threading import Lock

import numpy as np
import torch


SAMPLE_RATE = 48000

# One Silero v5.6 Russian model contains all three speaker IDs.
# "eugene" is the deeper male speaker; "xenia" is the friendly female speaker.
VOICE_PRESETS = {
    "normal": {
        "label": "Обычный мужской",
        "speaker": "aidar",
        "ffmpeg_options": "-af volume=1.15",
    },
    "pudge": {
        "label": "Пудж — глубокий басовый",
        "speaker": "eugene",
        "ffmpeg_options": "-af bass=g=5,volume=1.2",
    },
    "cute_girl": {
        "label": "Милая девушка",
        "speaker": "xenia",
        "ffmpeg_options": "-af volume=1.15",
    },
}

VOICE_PRESET_LABELS = {key: value["label"] for key, value in VOICE_PRESETS.items()}
VOICE_LABEL_TO_PRESET = {value["label"]: key for key, value in VOICE_PRESETS.items()}

LEGACY_VOICE_IDS = {
    "dmitry": "normal",
    "ru-RU-DmitryNeural": "normal",
    "svetlana": "cute_girl",
    "ru-RU-SvetlanaNeural": "cute_girl",
    "dariya": "cute_girl",
    "ru-RU-DariyaNeural": "cute_girl",
}


def resolve_voice_profile(selection: str | None) -> dict:
    key = LEGACY_VOICE_IDS.get(selection or "", selection or "normal")
    return dict(VOICE_PRESETS.get(key, VOICE_PRESETS["normal"]))


class LocalSileroTTS:
    """Loads one local Russian Silero model and synthesizes WAV files on CPU."""

    def __init__(self, model_path: str | Path, logger):
        self.model_path = Path(model_path)
        self.log = logger
        self.model = None
        self._load_lock = Lock()
        self._synthesis_lock = Lock()

    def load(self) -> None:
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Не найдена локальная модель голоса: {self.model_path}. "
                "Распакуйте ZIP полностью, включая папку voices."
            )

        with self._load_lock:
            if self.model is not None:
                return

            torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                # PyTorch only allows this before its inter-op pool is initialized.
                pass

            self.log("Загружаю локальную модель Silero v5.6 (один раз при запуске)…")
            importer = torch.package.PackageImporter(str(self.model_path))
            model = importer.load_pickle("tts_models", "model")
            model.to(torch.device("cpu"))
            self.model = model

            # Warm up the model before accepting voice requests.
            with torch.inference_mode():
                model.apply_tts(
                    text="Проверка локального голоса.",
                    speaker="aidar",
                    sample_rate=SAMPLE_RATE,
                )

    def synthesize_to_wav(self, text: str, speaker: str, target_path: str | Path) -> tuple[int, float]:
        if self.model is None:
            raise RuntimeError("Локальная модель голоса ещё не загружена.")

        target_path = Path(target_path)
        with self._synthesis_lock, torch.inference_mode():
            audio = self.model.apply_tts(
                text=text,
                speaker=speaker,
                sample_rate=SAMPLE_RATE,
            )

        if hasattr(audio, "detach"):
            samples = audio.detach().to("cpu").numpy()
        else:
            samples = np.asarray(audio)

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0 or not np.isfinite(samples).all():
            raise RuntimeError("Локальная модель вернула пустой или некорректный аудиосигнал.")

        peak = float(np.max(np.abs(samples)))
        if peak < 1e-5:
            raise RuntimeError("Локальная модель вернула тишину.")

        samples = np.clip(samples, -1.0, 1.0)
        pcm = (samples * 32767.0).astype(np.int16)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm.tobytes())

        duration = len(pcm) / SAMPLE_RATE
        return target_path.stat().st_size, duration
