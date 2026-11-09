import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.local_tts import LocalSileroTTS, VOICE_PRESETS, resolve_voice_profile


async def main_async() -> None:
    model_path = ROOT / "voices" / "v5_6_ru.pt"
    if not model_path.is_file():
        raise SystemExit(f"Silero model not found: {model_path}")

    tts = LocalSileroTTS(model_path, lambda _message: None)
    await asyncio.to_thread(tts.load)

    expected = {
        "normal": "aidar",
        "pudge": "eugene",
        "cute_girl": "xenia",
    }
    for preset, expected_speaker in expected.items():
        profile = resolve_voice_profile(preset)
        if profile["speaker"] != expected_speaker:
            raise AssertionError(f"{preset}: expected {expected_speaker}, got {profile}")

        output = ROOT / "tests" / f"silero-{preset}.wav"
        size, duration = await asyncio.to_thread(
            tts.synthesize_to_wav,
            "Привет! Это проверка локального русского голоса.",
            profile["speaker"],
            output,
        )
        if size < 2048 or duration < 0.25:
            raise AssertionError(
                f"{preset}: suspicious audio output size={size}, duration={duration}"
            )
        output.unlink(missing_ok=True)
        print(f"{preset}: speaker={expected_speaker}, {duration:.2f}s, {size} bytes")

    # Confirm that model inference does not starve the asyncio loop.
    samples = []
    async def heartbeat():
        for _ in range(10):
            await asyncio.sleep(0.05)
            samples.append(True)

    await asyncio.gather(
        heartbeat(),
        asyncio.to_thread(
            tts.synthesize_to_wav,
            "Проверка, что синтез не блокирует event loop.",
            "eugene",
            ROOT / "tests" / "silero-loop.wav",
        ),
    )
    (ROOT / "tests" / "silero-loop.wav").unlink(missing_ok=True)
    if len(samples) != 10:
        raise AssertionError("Event loop heartbeat did not complete during local synthesis")

    print("All three Silero voices synthesized; asyncio remained responsive.")


if __name__ == "__main__":
    asyncio.run(main_async())
