from __future__ import annotations

import gc
import importlib
import os
import sys
import wave
from pathlib import Path
from threading import Lock

import numpy as np


def _write_audio_wav(
    audio,
    sample_rate: int,
    target_path: str | Path,
    logger=None,
) -> tuple[int, float]:
    target_path = Path(target_path)
    if hasattr(audio, "detach"):
        samples = audio.detach().to("cpu").numpy()
    else:
        samples = np.asarray(audio)
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)

    if samples.size == 0 or not np.isfinite(samples).all():
        raise RuntimeError("Дополнительная модель вернула пустой или некорректный звук.")

    peak_before = float(np.max(np.abs(samples)))
    rms_before = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if peak_before < 1e-5 or rms_before < 1e-6:
        raise RuntimeError(
            f"Дополнительная модель вернула практически тишину "
            f"(peak={peak_before:.6f}, RMS={rms_before:.6f})."
        )

    # Some cross-lingual reference styles return valid speech at a much lower
    # amplitude than Silero. Normalize only this additional-TTS path; the
    # default and bear voices use LocalSileroTTS and are not affected.
    target_peak = 0.28
    max_gain = 128.0
    gain = min(target_peak / peak_before, max_gain)
    samples = samples * np.float32(gain)
    peak_after = float(np.max(np.abs(samples)))
    rms_after = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))

    if peak_after < 0.02 or rms_after < 0.001:
        raise RuntimeError(
            "Дополнительная модель выдала слишком слабый сигнал даже после "
            f"нормализации (peak={peak_after:.4f}, RMS={rms_after:.4f}, "
            f"усиление={gain:.1f}x). Сообщение не будет отправлено как будто звук исправен."
        )

    if logger:
        logger(
            "Уровень дополнительного голоса: "
            f"до peak={peak_before:.6f}/RMS={rms_before:.6f}; "
            f"усиление={gain:.1f}x; после peak={peak_after:.3f}/RMS={rms_after:.3f}."
        )

    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    return target_path.stat().st_size, len(pcm) / sample_rate


class TeraTTS:
    """Offline TeraTTSv2 runtime for Russian and cross-language accent styles."""

    SAMPLE_RATE = 44_100
    VOICE_STYLES = {"ru_m5", "eng_m4"}

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
                raise FileNotFoundError(f"Не найдена локальная модель TeraTTSv2: {script}")

            model_path = str(self.model_dir.resolve())
            if model_path not in sys.path:
                sys.path.insert(0, model_path)
            importlib.invalidate_caches()
            self.log("Загружаю TeraTTSv2 (локальный ONNX, CPU)…")
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
            self.log(f"TeraTTSv2 готова: CPUExecutionProvider, потоков={threads}.")

    def synthesize_to_wav(
        self,
        text: str,
        target_path: str | Path,
        voice_style: str = "ru_m5",
    ) -> tuple[int, float]:
        voice_style = str(voice_style or "ru_m5")
        if voice_style not in self.VOICE_STYLES:
            raise ValueError(f"Неподдерживаемый стиль TeraTTSv2: {voice_style}")
        prepared_text = str(text).strip()
        if not prepared_text:
            raise RuntimeError("Для озвучивания передан пустой текст.")

        self.load()
        # TeraSpace recommends starting at 0.8 when an English reference style
        # is used to speak Russian text. Keep the native Russian preset speed.
        duration_scale = 0.8 if voice_style.startswith("eng_") else 0.94
        with self._synthesis_lock:
            audio = self.module.generate_speech(
                self.model,
                f"<ru>{prepared_text}</ru>",
                voice_style,
                duration_scale=duration_scale,
                guidance=3.0,
            )
        return _write_audio_wav(audio, self.SAMPLE_RATE, target_path, logger=self.log)

    def unload(self) -> None:
        if self.model is not None:
            self.log("Освобождаю память TeraTTSv2…")
        self.model = None
        if self.module is not None:
            try:
                self.module.clear_session_cache()
            except Exception:
                pass
        self.module = None
        gc.collect()
