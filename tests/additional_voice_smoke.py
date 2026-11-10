import asyncio
import sys
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
        if duration < minimum_duration:
            raise AssertionError(f"Generated WAV is too short ({duration:.2f}s): {path}")
    print(f"{path.name}: {duration:.2f}s, {path.stat().st_size} bytes")


async def main_async() -> None:
    samples = ROOT / "tests" / "voice-samples"
    samples.mkdir(parents=True, exist_ok=True)

    import gc
    gc.collect()

    armenian_assets = ROOT / "voices" / "armenian"
    for required in ("armenian_tri.yaml", "tri_v1/model.safetensors", "tri_v1/tokenizer_tri.model", "armenian_reference.wav", "armenian_voice_state.safetensors"):
        if not (armenian_assets / required).is_file():
            raise AssertionError(f"Armenian voice resource is missing: {required}")
    armenian = ArmenianAccentTTS(armenian_assets, lambda _message: None)
    armenian_path = samples / "armenian-accent-ru.wav"
    try:
        size, duration = await asyncio.to_thread(
            armenian.synthesize_to_wav,
            "Привет! Это проверка русского текста с восточноармянским акцентом.",
            armenian_path,
        )
        check_wav(armenian_path)
    finally:
        armenian.unload()
        del armenian
        gc.collect()

    print("The Armenian accent voice loaded and produced a non-silent WAV sample.")


if __name__ == "__main__":
    asyncio.run(main_async())
