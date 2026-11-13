import asyncio
import math
import sys
import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.additional_tts import ArmenianAccentTTS


def check_wav(path: Path, minimum_size: int = 5000, minimum_duration: float = 0.5) -> None:
    import wave
    if not path.is_file() or path.stat().st_size < minimum_size:
        raise AssertionError(f"Generated WAV is missing or too small: {path}")
    with wave.open(str(path), "rb") as audio:
        duration = audio.getnframes() / float(audio.getframerate())
        pcm = array.array("h")
        pcm.frombytes(audio.readframes(audio.getnframes()))
        if duration < minimum_duration:
            raise AssertionError(f"Generated WAV is too short ({duration:.2f}s): {path}")
    if not pcm:
        raise AssertionError("Generated Armenian WAV contains no PCM samples")
    peak = max(abs(sample) for sample in pcm)
    rms = math.sqrt(sum(sample * sample for sample in pcm) / len(pcm))
    clipped_ratio = sum(abs(sample) >= 29490 for sample in pcm) / len(pcm)
    if peak < 500:
        raise AssertionError(f"Armenian WAV is nearly silent (peak={peak})")
    if peak >= 30000 or clipped_ratio > 0.001:
        raise AssertionError(
            f"Armenian WAV may be clipped (peak={peak}, clipped={clipped_ratio:.3%})"
        )
    if rms < 80:
        raise AssertionError(f"Armenian WAV RMS is too low ({rms:.1f})")
    print(
        f"{path.name}: {duration:.2f}s, peak={peak}, RMS={rms:.1f}, "
        f"clipped={clipped_ratio:.3%}, {path.stat().st_size} bytes"
    )


async def main_async() -> None:
    samples = ROOT / "tests" / "voice-samples"
    samples.mkdir(parents=True, exist_ok=True)

    import gc
    gc.collect()

    armenian_assets = ROOT / "voices" / "armenian"
    for required in ("armenian_tri.yaml", "tri_v1/model.safetensors", "tri_v1/tokenizer_tri.model", "armenian_reference.wav", "armenian_voice_state.safetensors"):
        if not (armenian_assets / required).is_file():
            raise AssertionError(f"Armenian voice resource is missing: {required}")
    diagnostics: list[str] = []
    armenian = ArmenianAccentTTS(armenian_assets, diagnostics.append)
    armenian_path = samples / "armenian-accent-ru.wav"
    try:
        size, duration = await asyncio.to_thread(
            armenian.synthesize_to_wav,
            "Привет! Это проверка русского текста с восточноармянским акцентом.",
            armenian_path,
        )
        check_wav(armenian_path)
        if not any("Армянский WAV подготовлен целиком" in line for line in diagnostics):
            raise AssertionError("Armenian WAV gain diagnostics were not emitted")
    finally:
        armenian.unload()
        del armenian
        gc.collect()

    print("The Armenian accent voice loaded and produced a non-silent WAV sample.")


if __name__ == "__main__":
    asyncio.run(main_async())
