from __future__ import annotations

import gc
import importlib
import os
import sys
import wave
from pathlib import Path
from threading import Lock

import numpy as np


def _write_audio_wav(audio, sample_rate: int, target_path: str | Path) -> tuple[int, float]:
    target_path = Path(target_path)
    if hasattr(audio, "detach"):
        samples = audio.detach().to("cpu").numpy()
    else:
        samples = np.asarray(audio)
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)

    if samples.size == 0 or not np.isfinite(samples).all():
        raise RuntimeError("Дополнительная модель вернула пустой или некорректный звук.")
    peak = float(np.max(np.abs(samples)))
    if peak < 1e-5:
        raise RuntimeError("Дополнительная модель вернула тишину.")

    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    return target_path.stat().st_size, len(pcm) / sample_rate


class TeraPopTTS:
    """Local TeraTTSv2 Russian male voice (ru_m5); no celebrity voice cloning."""

    SAMPLE_RATE = 44_100

    def __init__(self, model_dir: str | Path, logger):
        self.model_dir = Path(model_dir)
        self.log = logger
        self.module = None
        self.model = None
        self._load_lock = Lock()
        self._synthesis_lock = Lock()

    def load(self) -> None:
        if self.model is not None:
            return
        with self._load_lock:
            if self.model is not None:
                return
            script = self.model_dir / "teratts.py"
            if not script.is_file():
                raise FileNotFoundError(
                    f"Не найдена локальная модель молодого мужского голоса: {script}"
                )

            model_path = str(self.model_dir.resolve())
            if model_path not in sys.path:
                sys.path.insert(0, model_path)
            importlib.invalidate_caches()
            self.log("Загружаю локальную модель TeraTTSv2 (мужской голос ru_m5)…")
            module = importlib.import_module("teratts")
            threads = max(1, min(6, (os.cpu_count() or 2) // 2))
            loaded = module.load_model(
                self.model_dir,
                provider="CPUExecutionProvider",
                threads=threads,
                russian_stress=True,
                ruaccent_mode="dictionary",
            )
            self.module = module
            self.model = loaded
            self.log(f"TeraTTSv2 готова: CPUExecutionProvider, потоков={threads}, голос=ru_m5.")

    def synthesize_to_wav(self, text: str, target_path: str | Path) -> tuple[int, float]:
        self.load()
        with self._synthesis_lock:
            audio = self.module.generate_speech(
                self.model,
                f"<ru>{text}</ru>",
                "ru_m5",
                duration_scale=0.94,
                guidance=3.0,
            )
        return _write_audio_wav(audio, self.SAMPLE_RATE, target_path)

    def unload(self) -> None:
        if self.model is not None:
            self.log("Освобождаю память модели TeraTTSv2…")
        self.model = None
        if self.module is not None:
            try:
                self.module.clear_session_cache()
            except Exception:
                pass
        self.module = None
        gc.collect()


class ArmenianAccentTTS:
    """Russian speech conditioned on an anonymized Eastern Armenian speaker sample."""

    def __init__(self, model_dir: str | Path, logger):
        self.model_dir = Path(model_dir)
        self.log = logger
        self.model = None
        self.voice_state = None
        self._load_lock = Lock()
        self._synthesis_lock = Lock()

    def load(self) -> None:
        if self.model is not None:
            return
        with self._load_lock:
            if self.model is not None:
                return

            config_path = self.model_dir / "armenian_tri.yaml"
            reference_path = self.model_dir / "armenian_reference.wav"
            for path in (config_path, reference_path):
                if not path.is_file():
                    raise FileNotFoundError(f"Не найден ресурс армянского голоса: {path}")

            try:
                import torch
                from pocket_tts import TTSModel
            except ImportError as exc:
                raise RuntimeError(
                    "Для армянского голоса не установлены компоненты Pocket TTS."
                ) from exc

            torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
            self.log("Загружаю многоязычную модель Pocket TTS (армянский + русский)…")
            model = TTSModel.load_model(config=str(config_path))
            self.log("Подготавливаю тембр анонимизированного восточноармянского диктора…")
            voice_state = model.get_state_for_audio_prompt(str(reference_path))

            # The input is Russian. Core normalizes Russian numbers before TTS.
            # Do not load the Armenian-only hy_text.py: it is for Armenian-script
            # text and is not part of the Russian cross-lingual inference path.
            self.model = model
            self.voice_state = voice_state
            self.log("Армянский акцент готов: русский текст, восточноармянский референс.")

    def synthesize_to_wav(self, text: str, target_path: str | Path) -> tuple[int, float]:
        self.load()
        prepared_text = str(text).strip()
        if not prepared_text:
            raise RuntimeError("Для армянского голоса передан пустой текст.")

        with self._synthesis_lock:
            audio = self.model.generate_audio(
                self.voice_state,
                prepared_text,
                copy_state=True,
            )
        return _write_audio_wav(audio, self.model.sample_rate, target_path)

    def unload(self) -> None:
        if self.model is not None:
            self.log("Освобождаю память армянской модели…")
        self.voice_state = None
        self.model = None
        gc.collect()
