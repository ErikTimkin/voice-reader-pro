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

    sample_text = "Привет! Это проверка армянского акцента. Как дела? Сегодня хорошая погода."
    baseline_trials = []
    baseline_path = ROOT / "tests" / "silero-baseline-benchmark.wav"
    for _ in range(3):
        started = time.perf_counter()
        base_size, base_duration = await asyncio.to_thread(
            tts.synthesize_to_wav, sample_text, "aidar", baseline_path
        )
        base_elapsed = time.perf_counter() - started
        baseline_trials.append((base_elapsed, base_duration, base_elapsed / max(base_duration, 0.01)))
    baseline_elapsed, baseline_duration, baseline_rtf = sorted(
        baseline_trials, key=lambda item: item[2]
    )[1]
    baseline_path.unlink(missing_ok=True)

    cis_model_path = ROOT / "voices" / "v5_cis_base.pt"
    if not cis_model_path.is_file() or cis_model_path.stat().st_size < 50_000_000:
        raise SystemExit(f"Silero CIS Armenian model is missing or incomplete: {cis_model_path}")

    eastern_speakers = {
        "armenian2": "ru_safarhuja",
        "armenian3": "ru_eduard",
        "armenian4": "ru_marat",
    }
    eastern_tts = LocalSileroTTS(
        cis_model_path,
        lambda _message: None,
        warmup_speakers=tuple(eastern_speakers.values()),
        model_label="Silero v5 CIS Base",
        russian_accentor=True,
    )
    print("Loading and warming all three eastern-accent speakers...")
    load_started = time.perf_counter()
    await asyncio.to_thread(eastern_tts.load)
    load_elapsed = time.perf_counter() - load_started

    for preset, speaker in eastern_speakers.items():
        target = ROOT / "tests" / f"silero-{preset}.wav"
        trials = []
        for _ in range(3):
            started = time.perf_counter()
            size, duration = await asyncio.to_thread(
                eastern_tts.synthesize_to_wav,
                sample_text,
                speaker,
                target,
            )
            elapsed = time.perf_counter() - started
            trials.append((elapsed, duration, elapsed / max(duration, 0.01)))
        elapsed, duration, rtf = sorted(trials, key=lambda item: item[2])[1]
        if size < 5_000 or duration < 0.5:
            raise AssertionError(
                f"{preset} generated suspicious audio: {size} bytes, {duration:.2f}s"
            )
        if rtf > 1.5 or rtf > baseline_rtf * 1.75:
            raise AssertionError(
                f"{preset} CPU synthesis is too slow: {elapsed:.2f}s for "
                f"{duration:.2f}s of speech (median RTF={rtf:.2f}, "
                f"standard Silero median RTF={baseline_rtf:.2f}, limits=1.5 and "
                f"1.75x baseline)"
            )
        target.unlink(missing_ok=True)
        print(
            f"{preset} ({speaker}) median RTF={rtf:.2f}; "
            f"audio={duration:.2f}s/{size} bytes."
        )

    print(
        f"Standard Silero (aidar) median RTF={baseline_rtf:.2f}; "
        f"three eastern speakers warmed in {load_elapsed:.2f}s."
    )

    print("Male, female, cute and all three eastern-accent Silero CIS voices synthesized successfully.")


if __name__ == "__main__":
    asyncio.run(main_async())
