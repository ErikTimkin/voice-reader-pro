from __future__ import annotations

import gc
import importlib
import os
import re
import sys
import unicodedata
import tempfile
import wave
from pathlib import Path
from threading import Lock

import numpy as np
import yaml


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

    # TTS checkpoints can return valid but extremely quiet waveforms. Normalize
    # peak level before converting to int16 so the Armenian and pop voices are
    # audible through Discord's Opus pipeline. Keep headroom to avoid clipping.
    samples = samples * (0.85 / peak)
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
            release = self.model_dir.resolve()
            required = (
                release / "teratts.py",
                release / "unicode_indexer.json",
                release / "models" / "text_encoder.onnx",
                release / "models" / "duration_predictor.onnx",
                release / "models" / "sampler_distilled_cfg3_8step.onnx",
                release / "models" / "vocoder.onnx",
                release / "styles" / "ru_m5" / "style_ttl.npy",
                release / "styles" / "ru_m5" / "style_dp.npy",
            )
            missing = [path for path in required if not path.is_file()]
            if missing:
                raise FileNotFoundError(
                    "Неполный пакет молодого поп-голоса; отсутствуют файлы: "
                    + ", ".join(str(path) for path in missing)
                )
            if not (release / "ruaccent").is_dir():
                raise FileNotFoundError(
                    f"Не найдена папка RUAccent молодого поп-голоса: {release / 'ruaccent'}"
                )

            model_path = str(release)
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


def normalize_russian_for_pocket_tts(text: str) -> str:
    """Prepare Russian text for the tri_v1 Pocket TTS checkpoint.

    The checkpoint's training notes require language-specific text
    normalization. Numbers are expanded by Voice Reader's shared normalizer
    before this function; here we canonicalize Unicode, punctuation and
    whitespace so the SentencePiece tokenizer sees the expected Russian text.
    """
    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.replace("ё", "ё").replace("Ё", "Ё")
    value = value.translate(str.maketrans({
        "—": "-", "–": "-", "−": "-",
        "“": '"', "”": '"', "„": '"',
        "’": "'", "‘": "'", "…": "...",
        "\u00a0": " ", "\u2009": " ", "\u202f": " ",
    }))
    value = re.sub(r"[\t\r\f\v ]+", " ", value)
    value = re.sub(r" *([,;:!?]) *", r"\1 ", value)
    value = re.sub(r"\.\s*\.\s*\.", "...", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


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
            voice_state_path = self.model_dir / "armenian_voice_state.safetensors"
            weights_path = self.model_dir / "tri_v1" / "model.safetensors"
            tokenizer_path = self.model_dir / "tri_v1" / "tokenizer_tri.model"
            required = (config_path, reference_path, weights_path, tokenizer_path)
            missing = [path for path in required if not path.is_file()]
            if missing:
                raise FileNotFoundError(
                    "Неполный пакет армянского голоса; отсутствуют файлы: "
                    + ", ".join(str(path) for path in missing)
                )

            try:
                import torch
                from pocket_tts import TTSModel
            except ImportError as exc:
                raise RuntimeError(
                    "Для армянского голоса не установлены компоненты Pocket TTS."
                ) from exc

            # The build-time YAML must never dictate paths on the user's PC.
            # CI used to write absolute D:\\a\\... paths into this file. Those
            # paths exist on the GitHub runner, not on another Windows machine.
            # Resolve the two model assets from this installation's voices folder
            # and pass Pocket TTS a temporary portable config.
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            config["weights_path"] = str(weights_path.resolve())
            config.pop("weights_path_without_voice_cloning", None)
            config["flow_lm"]["lookup_table"]["tokenizer_path"] = str(
                tokenizer_path.resolve()
            )

            runtime_config_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=".yaml",
                    prefix="voice-reader-armenian-",
                    delete=False,
                ) as runtime_config:
                    yaml.safe_dump(
                        config,
                        runtime_config,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                    runtime_config_path = Path(runtime_config.name)

                # Pocket TTS is CPU-bound; allow up to six threads on modern
                # desktop CPUs while keeping enough headroom for Discord.
                # Leave CPU headroom for Discord's asyncio gateway and voice heartbeats.
                torch.set_num_threads(max(1, min(2, os.cpu_count() or 2)))
                try:
                    torch.set_num_interop_threads(1)
                except RuntimeError:
                    # PyTorch only allows this before its inter-op pool is initialized.
                    pass
                self.log("Загружаю многоязычную модель Pocket TTS (армянский + русский)…")
                model = TTSModel.load_model(config=str(runtime_config_path))
            finally:
                if runtime_config_path is not None:
                    runtime_config_path.unlink(missing_ok=True)

            if voice_state_path.is_file():
                self.log("Загружаю заранее подготовленный тембр армянского диктора…")
                voice_state = model.get_state_for_audio_prompt(str(voice_state_path))
            else:
                self.log("Подготавливаю тембр анонимизированного восточноармянского диктора…")
                voice_state = model.get_state_for_audio_prompt(str(reference_path))
                try:
                    from pocket_tts import export_model_state
                    export_model_state(voice_state, voice_state_path)
                    self.log("Тембр сохранён для ускорения следующих запусков.")
                except Exception as exc:
                    self.log(f"Не удалось сохранить кэш тембра (продолжаю без него): {exc}")

            # The input is Russian. Core normalizes Russian numbers before TTS.
            # Do not load the Armenian-only hy_text.py: it is for Armenian-script
            # text and is not part of the Russian cross-lingual inference path.
            self.model = model
            self.voice_state = voice_state

            # Loading weights and the speaker prompt does not initialize every
            # inference/decoder path. Run a tiny throwaway stream now, while the
            # app is starting, so the first real Discord request does not pay
            # the one-time CPU/kernel/cache setup cost.
            warmup_started = __import__("time").perf_counter()
            warmup_samples = 0
            for warmup_chunk in self.model.generate_audio_stream(
                self.voice_state,
                "Привет.",
                copy_state=True,
            ):
                if hasattr(warmup_chunk, "numel"):
                    warmup_samples += int(warmup_chunk.numel())
                else:
                    warmup_samples += int(np.asarray(warmup_chunk).size)
            if warmup_samples <= 0:
                raise RuntimeError("Pocket TTS не выдал звук во время прогрева армянской модели.")
            warmup_ms = (__import__("time").perf_counter() - warmup_started) * 1000
            self.log(
                f"Армянская модель прогрета: тестовый звук={warmup_samples / model.sample_rate:.2f} сек, "
                f"время прогрева={warmup_ms:.0f} мс."
            )
            self.log("Армянский акцент готов: русский текст, восточноармянский референс.")

    def synthesize_to_wav(self, text: str, target_path: str | Path) -> tuple[int, float]:
        self.load()
        prepared_text = normalize_russian_for_pocket_tts(text)
        if not prepared_text:
            raise RuntimeError("Для армянского голоса передан пустой текст.")

        with self._synthesis_lock:
            audio = self.model.generate_audio(
                self.voice_state,
                prepared_text,
                copy_state=True,
            )
        return _write_audio_wav(audio, self.model.sample_rate, target_path)

    def stream_to_source(self, text: str, source) -> None:
        """Generate Armenian speech incrementally into a Discord PCM source."""
        self.load()
        prepared_text = normalize_russian_for_pocket_tts(text)
        if not prepared_text:
            raise RuntimeError("Для армянского голоса передан пустой текст.")
        import time
        started = time.perf_counter()
        first_chunk_ms = None
        chunks = 0
        sample_count = 0
        peak = 0.0
        with self._synthesis_lock:
            for chunk in self.model.generate_audio_stream(
                self.voice_state,
                prepared_text,
                copy_state=True,
                stop=source.stop_event,
            ):
                if source.stop_event.is_set():
                    break
                if hasattr(chunk, "detach"):
                    samples = chunk.detach().to("cpu").numpy()
                else:
                    samples = np.asarray(chunk)
                samples = np.asarray(samples, dtype=np.float32).reshape(-1)
                if samples.size == 0:
                    continue
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - started) * 1000
                chunks += 1
                sample_count += int(samples.size)
                peak = max(peak, float(np.max(np.abs(samples))))
                # Pocket TTS emits 24 kHz mono. Discord PCM expects 48 kHz,
                # 16-bit stereo, in exact 20 ms frames (3,840 bytes).
                source.push_mono_24k(samples)
        elapsed = time.perf_counter() - started
        audio_seconds = sample_count / float(self.model.sample_rate)
        rtf = (elapsed / audio_seconds) if audio_seconds > 0 else float("inf")
        self.log(
            f"Армянский синтез: первый чанк={first_chunk_ms:.0f} мс; "
            f"чанков={chunks}; длительность={audio_seconds:.2f} сек; "
            f"генерация={elapsed:.2f} сек; RTF={rtf:.2f}; peak={peak:.4f}."
            if first_chunk_ms is not None else
            f"Армянский синтез: модель не выдала чанков; время={elapsed:.2f} сек."
        )
        if sample_count and peak < 1e-5:
            source.finish(RuntimeError("Pocket TTS вернул цифровую тишину."))
            return
        source.finish()

    def unload(self) -> None:
        if self.model is not None:
            self.log("Освобождаю память армянской модели…")
        self.voice_state = None
        self.model = None
        gc.collect()
