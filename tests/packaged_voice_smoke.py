from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
import wave
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.additional_tts import ArmenianAccentTTS
from voice_reader.local_tts import LocalSileroTTS


def verify_wav(path: Path, minimum_bytes: int = 5_000) -> None:
    if not path.is_file() or path.stat().st_size < minimum_bytes:
        raise AssertionError(f"Voice did not create a valid WAV file: {path}")
    with wave.open(str(path), "rb") as wav:
        duration = wav.getnframes() / float(wav.getframerate())
    if duration < 0.5:
        raise AssertionError(f"Voice output is unexpectedly short: {duration:.2f}s")
    print(f"{path.name}: {duration:.2f}s, {path.stat().st_size} bytes")


async def main_async(source_voices: Path) -> None:
    source_voices = source_voices.resolve()
    cis_model = source_voices / "v5_cis_base.pt"
    if not cis_model.is_file() or cis_model.stat().st_size < 50_000_000:
        raise AssertionError(f"Packaged Silero CIS model is missing or incomplete: {cis_model}")
    for relative in (
        Path("armenian/armenian_tri.yaml"),
        Path("armenian/armenian_reference.wav"),
        Path("armenian/armenian_voice_state.safetensors"),
        Path("armenian/tri_v1/model.safetensors"),
        Path("armenian/tri_v1/tokenizer_tri.model"),
    ):
        if not (source_voices / relative).is_file():
            raise AssertionError(f"Packaged voice resource is missing: {relative}")

    generated_config = (source_voices / "armenian" / "armenian_tri.yaml").read_text(
        encoding="utf-8"
    )
    if "__VOICE_ASSET_ROOT__" not in generated_config:
        raise AssertionError("Armenian config must use portable path markers, not CI absolute paths")
    if "D:\\\\a\\\\voice-reader-pro" in generated_config:
        raise AssertionError("Armenian config contains a GitHub runner path")

    # Copy just the external model folders to a new, unrelated path. This makes
    # the test fail if either engine relies on the original build workspace.
    with tempfile.TemporaryDirectory(prefix="voice-reader-portable-install-") as temp:
        relocated = Path(temp) / "portable-install" / "voices"
        relocated.mkdir(parents=True)
        shutil.copytree(source_voices / "armenian", relocated / "armenian")
        armenian = ArmenianAccentTTS(
            relocated / "armenian", lambda _message: None
        )
        armenian_wav = Path(temp) / "portable-armenian.wav"
        try:
            await asyncio.to_thread(
                armenian.synthesize_to_wav,
                "Проверка армянского акцента после переноса папки.",
                armenian_wav,
            )
            verify_wav(armenian_wav)
        finally:
            armenian.unload()

    with tempfile.TemporaryDirectory(prefix="voice-reader-silero-cis-portable-") as temp:
        relocated_model = Path(temp) / "voices" / "v5_cis_base.pt"
        relocated_model.parent.mkdir(parents=True)
        shutil.copy2(cis_model, relocated_model)
        silero_cis = LocalSileroTTS(
            relocated_model,
            print,
            warmup_speakers=("ru_zara",),
            model_label="Silero v5 CIS Base",
            russian_accentor=True,
        )
        cis_wav = Path(temp) / "portable-armenian2.wav"
        await asyncio.to_thread(silero_cis.load)
        await asyncio.to_thread(
            silero_cis.synthesize_to_wav,
            "Проверка русского текста с армянским тембром.",
            "ru_zara",
            cis_wav,
        )
        verify_wav(cis_wav)

    print("Original Armenian and Armenian 2.0 voices synthesized from relocated offline packages.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices-dir", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main_async(args.voices_dir))


if __name__ == "__main__":
    main()
