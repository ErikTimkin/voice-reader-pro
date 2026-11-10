import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.additional_tts import TeraTTS


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
    tera = TeraTTS(ROOT / "voices" / "teratts", lambda _message: None)

    try:
        pop_path = samples / "young-pop-ru.wav"
        await asyncio.to_thread(
            tera.synthesize_to_wav,
            "Привет! Это проверка молодого мужского голоса. Сегодня отличный день!",
            pop_path,
            "ru_m5",
        )
        check_wav(pop_path)

        accent_path = samples / "foreign-accent-ru.wav"
        await asyncio.to_thread(
            tera.synthesize_to_wav,
            "Брат, здравствуйте. Я уже подъехал, выходите, пожалуйста, к подъезду. "
            "До центра поедем через мост, там сейчас пробка.",
            accent_path,
            "eng_m4",
        )
        check_wav(accent_path)
    finally:
        tera.unload()

    print("Russian pop and foreign-accent male voices both produced non-silent WAV samples.")


if __name__ == "__main__":
    asyncio.run(main_async())
