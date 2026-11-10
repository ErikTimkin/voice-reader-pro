from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np

from voice_reader.additional_tts import _write_audio_wav


def main() -> None:
    # Simulate a model that returns a valid waveform at a very low amplitude.
    source = (np.sin(np.linspace(0, 80 * np.pi, 24_000)) * 0.002).astype(np.float32)
    with tempfile.TemporaryDirectory(prefix="voice-reader-audio-test-") as temp:
        output = Path(temp) / "normalized.wav"
        size, duration = _write_audio_wav(source, 24_000, output)
        with wave.open(str(output), "rb") as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            peak = int(np.max(np.abs(samples)))
            actual_duration = wav.getnframes() / wav.getframerate()
        if size <= 44 or duration < 0.9 or actual_duration < 0.9:
            raise AssertionError("WAV export produced an empty or truncated file.")
        if not 27_000 <= peak <= 28_000:
            raise AssertionError(f"Audio peak was not normalized safely: {peak}")
        print(f"Audio export normalization passed: peak={peak}, duration={duration:.2f}s.")


if __name__ == "__main__":
    main()
