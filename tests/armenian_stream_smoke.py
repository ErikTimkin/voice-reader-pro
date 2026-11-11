import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from voice_reader.additional_tts import _normalize_tts_samples
from voice_reader.core import StreamingPCMSource


def main() -> None:
    # Pocket TTS has returned valid Armenian speech at a peak around 0.0011.
    quiet_wave = np.sin(np.linspace(0, 30, 1920, dtype=np.float32)) * 0.0011
    normalized, raw_peak, normalized_peak = _normalize_tts_samples(quiet_wave)
    if not 0.0010 <= raw_peak <= 0.0012:
        raise AssertionError(f"Unexpected fixture peak: {raw_peak}")
    if not 0.84 <= normalized_peak <= 0.86:
        raise AssertionError(f"Quiet TTS audio was not normalized: {normalized_peak}")

    source = StreamingPCMSource(lambda _message: None)
    source.push_mono_24k(normalized)
    source.finish()
    frames = []
    while True:
        frame = source.read()
        if not frame:
            break
        if len(frame) != StreamingPCMSource.FRAME_BYTES:
            raise AssertionError(f"Discord PCM frame has wrong size: {len(frame)}")
        frames.append(frame)
    if len(frames) != 4:
        raise AssertionError(f"Expected four 20 ms frames from an 80 ms chunk, got {len(frames)}")
    pcm = np.frombuffer(b"".join(frames), dtype=np.int16)
    if int(np.max(np.abs(pcm))) < 27000:
        raise AssertionError("Normalized Armenian PCM is still too quiet.")

    failed_source = StreamingPCMSource(lambda _message: None)
    expected_error = RuntimeError("simulated Pocket TTS failure")
    failed_source.finish(expected_error)
    try:
        failed_source.read()
    except RuntimeError as exc:
        if str(expected_error) not in str(exc):
            raise AssertionError(f"Stream error detail was lost: {exc}") from exc
    else:
        raise AssertionError("Armenian stream source swallowed its synthesis error")

    print(
        "PASS: quiet Armenian TTS normalization, PCM framing and stream-error propagation "
        f"(raw_peak={raw_peak:.6f}, pcm_peak={int(np.max(np.abs(pcm)))})"
    )


if __name__ == "__main__":
    main()
