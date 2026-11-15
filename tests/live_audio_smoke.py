"""Deterministic smoke test for the live DSP chain (no microphone required)."""
from pathlib import Path
import sys

# GitHub Actions executes this file as python tests/live_audio_smoke.py.
# In that mode Python puts the tests directory, not the repository root, at
# sys.path[0]. Add the project root explicitly so the package import is stable
# on Windows runners as well as local launches.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from voice_reader.live_audio import LiveVoiceEngine, PRESETS, SAMPLE_RATE


def main():
    engine = LiveVoiceEngine()
    t = np.arange(SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    source = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    for preset in PRESETS:
        engine.configure(preset)
        result = engine.process_block(source)
        assert result.shape == source.shape, (preset, result.shape)
        assert np.isfinite(result).all(), preset
        assert float(np.max(np.abs(result))) <= 1.0, preset
        assert float(np.max(np.abs(result))) > 0.00001, preset
    engine.configure("Обычный", {"pitch": -2, "bass": 3, "treble": -2, "drive": 4})
    custom = engine.process_block(source)
    assert custom.shape == source.shape and np.isfinite(custom).all()
    engine.close()
    print("PASS: six live DSP presets and custom settings")


if __name__ == "__main__":
    main()
