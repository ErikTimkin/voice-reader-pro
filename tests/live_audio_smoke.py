"""Deterministic tests for the live DSP chain; no microphone is required."""
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from voice_reader.live_audio import BLOCK_SIZE, LiveVoiceEngine, PRESETS, SAMPLE_RATE


def dominant_frequency(audio: np.ndarray, sample_rate: int, expected: float) -> float:
    segment = np.asarray(audio[-sample_rate:], dtype=np.float32)
    windowed = segment * np.hanning(segment.size)
    spectrum = np.abs(np.fft.rfft(windowed, n=sample_rate * 4))
    frequencies = np.fft.rfftfreq(sample_rate * 4, 1.0 / sample_rate)
    band = (frequencies >= expected * 0.85) & (frequencies <= expected * 1.15)
    if not np.any(band):
        raise AssertionError("Pitch-check frequency band is empty")
    return float(frequencies[band][np.argmax(spectrum[band])])


def process_variable_blocks(engine: LiveVoiceEngine, source: np.ndarray) -> np.ndarray:
    sizes = (960, 512, 1024, 256, 480)
    output = []
    offset = 0
    block_index = 0
    while offset < source.size:
        count = min(sizes[block_index % len(sizes)], source.size - offset)
        output.append(engine.process_block(source[offset:offset + count]))
        offset += count
        block_index += 1
    return np.concatenate(output)


def main() -> None:
    sample_rate = SAMPLE_RATE
    duration_seconds = 2
    source_frequency = 1_000.0
    t = np.arange(sample_rate * duration_seconds, dtype=np.float32) / sample_rate
    source = (0.15 * np.sin(2.0 * np.pi * source_frequency * t)).astype(np.float32)

    measured = {}
    for preset, settings in PRESETS.items():
        engine = LiveVoiceEngine()
        try:
            engine.configure(preset)
            result = process_variable_blocks(engine, source)
            assert result.shape == source.shape, (preset, result.shape)
            assert np.isfinite(result).all(), preset
            assert float(np.max(np.abs(result))) <= 1.0, preset
            rms = float(np.sqrt(np.mean(np.square(result[-sample_rate // 2:]))))
            assert rms > 0.002, (preset, f"RMS too low: {rms:.6f}")

            semitones = float(settings.get("pitch", 0.0))
            if abs(semitones) >= 0.1:
                expected = source_frequency * (2.0 ** (semitones / 12.0))
                actual = dominant_frequency(result, sample_rate, expected)
                relative_error = abs(actual - expected) / expected
                assert relative_error <= 0.04, (
                    preset, f"expected {expected:.1f} Hz, got {actual:.1f} Hz"
                )
                measured[preset] = (actual, expected, relative_error)
        finally:
            engine.close()

    # Effect changes must replace the DSP chain cleanly without restarting it.
    engine = LiveVoiceEngine()
    try:
        engine.configure("Низкий")
        # Fill the 120 ms delay line as a live microphone would before the
        # user changes the selected effect.
        low = None
        for offset in range(0, sample_rate // 4, BLOCK_SIZE):
            low = engine.process_block(source[offset:offset + BLOCK_SIZE])
        engine.configure("Высокий")
        high = engine.process_block(source[:BLOCK_SIZE])
        assert np.isfinite(low).all() and np.isfinite(high).all()
        assert np.max(np.abs(low)) > 1e-5 and np.max(np.abs(high)) > 1e-5

        engine.configure("Обычный", {"pitch": -2, "bass": 3, "treble": -2, "drive": 4})
        custom = engine.process_block(source[:BLOCK_SIZE])
        assert custom.shape == source[:BLOCK_SIZE].shape and np.isfinite(custom).all()
        assert np.max(np.abs(custom)) > 1e-5

        # A 20 ms callback must finish comfortably inside its audio deadline.
        timings_ms = []
        noise = np.random.default_rng(7).normal(0.0, 0.03, BLOCK_SIZE).astype(np.float32)
        for _ in range(200):
            started = time.perf_counter()
            engine.process_block(noise)
            timings_ms.append((time.perf_counter() - started) * 1000.0)
        p95_ms = float(np.percentile(timings_ms, 95))
        p99_ms = float(np.percentile(timings_ms, 99))
        callback_budget_ms = BLOCK_SIZE / sample_rate * 1000.0
        assert p95_ms < callback_budget_ms, (
            f"DSP p95 {p95_ms:.2f} ms exceeds {callback_budget_ms:.2f} ms callback budget"
        )
    finally:
        engine.close()

    ascii_labels = {"Низкий": "low", "Высокий": "high", "Демон": "demon"}
    for preset, (actual, expected, error) in measured.items():
        label = ascii_labels.get(preset, "pitch")
        print(f"{label}: measured={actual:.2f}Hz target={expected:.2f}Hz error={error:.2%}")
    print(
        "PASS: six DSP presets, non-silent audio, pitch accuracy, variable callback blocks, "
        f"live reconfiguration and callback timing (p95={p95_ms:.2f}ms, p99={p99_ms:.2f}ms)"
    )


if __name__ == "__main__":
    main()
