from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg.exe"
PITCH_FILTER = "asetrate=42240,aresample=48000"
FULL_FILTER = f"{PITCH_FILTER},atempo=1.136,bass=g=5:f=150,lowpass=f=5200,acompressor=threshold=0.12:ratio=2.2:attack=8:release=90,volume=1.2"


def render(ffmpeg: Path, source: str, filters: str, output: Path) -> None:
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", source, "-af", filters,
        "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le",
        "-y", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 or not output.is_file():
        raise AssertionError(f"Jelly Bear FFmpeg filter failed: {result.stderr}")


def read_wav(path: Path) -> tuple[int, np.ndarray, float]:
    with wave.open(str(path), "rb") as audio:
        rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16)
    return rate, samples, len(samples) / rate


def dominant_frequency(samples: np.ndarray, rate: int) -> float:
    # Ignore edge transients and analyze the steady-state middle of the tone.
    start = len(samples) // 5
    end = len(samples) * 4 // 5
    window = samples[start:end].astype(np.float64)
    window -= window.mean()
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    frequencies = np.fft.rfftfreq(len(window), 1.0 / rate)
    return float(frequencies[int(np.argmax(spectrum))])


def main() -> None:
    if not FFMPEG.is_file():
        raise SystemExit(f"Bundled FFmpeg not found: {FFMPEG}")

    with tempfile.TemporaryDirectory(prefix="voice-reader-jelly-filter-") as temp:
        temp_dir = Path(temp)
        pitch_output = temp_dir / "pitch-only.wav"
        full_output = temp_dir / "full-filter.wav"

        # Verify the pitch-shift stage independently. The following atempo
        # stage is a time-stretcher; measuring a pure sine after WSOLA can
        # produce misleading spectral peaks even when speech sounds correct.
        render(FFMPEG, "sine=frequency=440:sample_rate=48000:duration=1", PITCH_FILTER, pitch_output)
        pitch_rate, pitch_samples, pitch_duration = read_wav(pitch_output)
        if pitch_rate != 48000 or not 0.75 <= pitch_duration <= 0.9:
            raise AssertionError(
                f"Unexpected pitch-stage format/duration: {pitch_rate} Hz, {pitch_duration:.3f}s"
            )
        measured = dominant_frequency(pitch_samples, pitch_rate)
        expected = 440.0 * 42240.0 / 48000.0
        if abs(measured - expected) > 5.0:
            raise AssertionError(
                f"Pitch stage should raise 440 Hz to about {expected:.1f} Hz: got {measured:.1f} Hz"
            )

        # Exercise the exact complete production filter and ensure it returns
        # valid, audible 48 kHz PCM with the expected near-original duration.
        render(FFMPEG, "sine=frequency=440:sample_rate=48000:duration=1", FULL_FILTER, full_output)
        full_rate, full_samples, full_duration = read_wav(full_output)
        if full_rate != 48000 or not 0.95 <= full_duration <= 1.05:
            raise AssertionError(
                f"Unexpected full-filter format/duration: {full_rate} Hz, {full_duration:.3f}s"
            )
        if full_samples.size == 0 or int(np.max(np.abs(full_samples))) < 1000:
            raise AssertionError("Full Jelly Bear filter produced silent or empty audio")

        print(
            f"PASS: Jelly Bear filter; pitch-stage={measured:.1f} Hz "
            f"(target {expected:.1f}), full-duration={full_duration:.3f}s, "
            f"sample_rate={full_rate} Hz."
        )


if __name__ == "__main__":
    main()
