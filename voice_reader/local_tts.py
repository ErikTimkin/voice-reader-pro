from __future__ import annotations

import os
import wave
from pathlib import Path
from threading import Lock

import numpy as np
import torch

SAMPLE_RATE = 48000

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

            # Warm up every speaker used by the UI before accepting requests.
            # The first Xenia request otherwise pays speaker-specific setup time.
            with torch.inference_mode():
                for speaker in ("aidar", "baya", "xenia"):
                    warmup_audio = model.apply_tts(
                        text="Проверка локального голоса.",
                        speaker=speaker,
                        sample_rate=SAMPLE_RATE,
                    )
                    if warmup_audio is None or len(warmup_audio) == 0:
                        raise RuntimeError(f"Silero не прогрела голос {speaker}.")
                    self.log(f"Голос Silero {speaker} прогрет.")

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
