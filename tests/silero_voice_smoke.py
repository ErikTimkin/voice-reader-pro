import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.local_tts import LocalSileroTTS
from voice_reader.voice_profiles import resolve_voice_profile


async def main_async() -> None:
    model_path = ROOT / "voices" / "v5_6_ru.pt"
    if not model_path.is_file() or model_path.stat().st_size < 50_000_000:
        raise SystemExit(f"Silero model is missing or incomplete: {model_path}")

    tts = LocalSileroTTS(model_path, lambda _message: None)
    await asyncio.to_thread(tts.load)
    for preset, expected_speaker in (("normal", "aidar"), ("female", "baya"), ("cute_girl", "xenia")):
        profile = resolve_voice_profile(preset)
        if profile["speaker"] != expected_speaker:
            raise AssertionError(f"{preset}: expected speaker {expected_speaker}, got {profile}")
        target = ROOT / "tests" / f"silero-{preset}.wav"
        size, duration = await asyncio.to_thread(
            tts.synthesize_to_wav,
            "Привет! Проверка голоса Voice Reader Pro.",
            profile["speaker"],
            target,
        )
        if size < 2048 or duration < 0.25:
            raise AssertionError(f"{preset}: suspicious audio output size={size}, duration={duration}")
        target.unlink(missing_ok=True)
        print(f"{preset}: {expected_speaker}, {duration:.2f}s, {size} bytes")

    cis_model_path = ROOT / "voices" / "v5_cis_base.pt"
    if not cis_model_path.is_file() or cis_model_path.stat().st_size < 50_000_000:
        raise SystemExit(f"Silero CIS Armenian model is missing or incomplete: {cis_model_path}")

    armenian2 = LocalSileroTTS(
        cis_model_path,
        print,
        warmup_speakers=("ru_zara",),
        model_label="Silero v5 CIS Base",
        russian_accentor=True,
    )
    print("Loading Armenian 2.0 model and Russian stress dictionary...")
    await asyncio.to_thread(armenian2.load)
    target = ROOT / "tests" / "silero-armenian2.wav"
    started = time.perf_counter()
    size, duration = await asyncio.to_thread(
        armenian2.synthesize_to_wav,
        "Привет! Это проверка армянского акцента. Как дела? Сегодня хорошая погода.",
        "ru_zara",
        target,
    )
    elapsed = time.perf_counter() - started
    if size < 5_000 or duration < 0.5:
        raise AssertionError(
            f"Armenian 2.0 generated suspicious audio: {size} bytes, {duration:.2f}s"
        )
    rtf = elapsed / duration
    if rtf > 4.0:
        raise AssertionError(
            f"Armenian 2.0 CPU synthesis is too slow: {elapsed:.2f}s for "
            f"{duration:.2f}s of speech (RTF={rtf:.2f}, limit=4.0)"
        )
    target.unlink(missing_ok=True)
    print(
        f"Armenian 2.0: ru_zara, {duration:.2f}s audio in {elapsed:.2f}s "
        f"(RTF={rtf:.2f}); WAV={size} bytes."
    )

    print("Male, female, cute and Armenian 2.0 Silero voices synthesized successfully.")


if __name__ == "__main__":
    asyncio.run(main_async())
