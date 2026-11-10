from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg.exe"
FILTER = "asetrate=57120,aresample=48000,atempo=0.84,volume=1.15"


def main() -> None:
    if not FFMPEG.is_file():
        raise SystemExit(f"Bundled FFmpeg not found: {FFMPEG}")

    with tempfile.TemporaryDirectory(prefix="voice-reader-jelly-filter-") as temp:
        output = Path(temp) / "jelly-filter.wav"
        command = [
            str(FFMPEG), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-af", FILTER, "-ac", "1", "-ar", "48000",
            "-c:a", "pcm_s16le", "-y", str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not output.is_file():
            raise AssertionError(f"Jelly Bear FFmpeg filter failed: {result.stderr}")

        with wave.open(str(output), "rb") as audio:
            rate = audio.getframerate()
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16)
            duration = len(samples) / rate

        if rate != 48000 or not 0.88 <= duration <= 1.05:
            raise AssertionError(f"Unexpected filtered audio format/duration: {rate} Hz, {duration:.3f}s")
        window = samples.astype(np.float64)
        window -= window.mean()
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
        frequencies = np.fft.rfftfreq(len(window), 1.0 / rate)
        measured = float(frequencies[int(np.argmax(spectrum))])
        expected = 440.0 * 57120.0 / 48000.0
        if abs(measured - expected) > 8.0:
            raise AssertionError(
                f"Pitch filter did not raise 440 Hz to about {expected:.1f} Hz: got {measured:.1f} Hz"
            )
        print(
            f"PASS: Jelly Bear FFmpeg filter; pitch={measured:.1f} Hz, "
            f"duration={duration:.3f}s, sample_rate={rate} Hz."
        )


if __name__ == "__main__":
    main()
