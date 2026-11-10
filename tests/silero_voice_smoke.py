import asyncio
import sys
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
    for preset, expected_speaker in (("normal", "aidar"), ("cute_girl", "xenia")):
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
        import numpy as np
        import wave
        with wave.open(str(target), "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16).astype(np.float64)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        if size < 2048 or duration < 0.25 or peak < 5000 or rms < 250:
            raise AssertionError(
                f"{preset}: suspicious audio output size={size}, duration={duration}, "
                f"peak={peak:.0f}, RMS={rms:.1f}"
            )
        target.unlink(missing_ok=True)
        print(f"{preset}: {expected_speaker}, {duration:.2f}s, {size} bytes")

    print("Default male and female Silero voices synthesized successfully.")


if __name__ == "__main__":
    asyncio.run(main_async())
