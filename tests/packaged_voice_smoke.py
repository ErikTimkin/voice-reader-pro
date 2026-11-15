from __future__ import annotations

import argparse
import asyncio
import tempfile
import wave
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
    with tempfile.TemporaryDirectory(prefix="voice-reader-cis-portable-", ignore_cleanup_errors=True) as temp:
        relocated_model = Path(temp) / "voices" / "v5_cis_base.pt"
        relocated_model.parent.mkdir(parents=True)
        import shutil
        shutil.copy2(cis_model, relocated_model)
        tts = LocalSileroTTS(
            relocated_model,
            lambda _message: None,
            warmup_speakers=("ru_safarhuja", "ru_eduard", "ru_marat"),
            model_label="Silero v5 CIS Base",
            russian_accentor=True,
        )
        await asyncio.to_thread(tts.load)
        for preset, speaker in (
            ("armenian2", "ru_safarhuja"),
            ("armenian3", "ru_eduard"),
            ("armenian4", "ru_marat"),
        ):
            target = Path(temp) / f"portable-{preset}.wav"
            await asyncio.to_thread(
                tts.synthesize_to_wav,
                "Проверка русского текста с восточным акцентом.",
                speaker,
                target,
            )
            verify_wav(target)
    print("All three retained eastern-accent CIS voices synthesized from a relocated offline package.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices-dir", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main_async(args.voices_dir))


if __name__ == "__main__":
    main()
