import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import array

import numpy as np
from voice_reader.additional_tts import _stream_normalization_gain
from voice_reader.core import StreamingPCMSource


def main() -> None:
    # Reproduce the very quiet Pocket TTS level observed in the Discord logs.
    quiet = np.sin(np.linspace(0, 30, 1920, dtype=np.float32)) * 0.0011
    gain = _stream_normalization_gain(float(np.max(np.abs(quiet))))
    normalized = quiet * gain
    if float(np.max(np.abs(normalized))) < 0.20:
        raise AssertionError("Low-level Armenian speech was not amplified enough")

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
    if not any(any(frame) for frame in frames):
        raise AssertionError("Stream conversion produced silence")
    pcm = array.array("h")
    for frame in frames:
        pcm.frombytes(frame)
    if max(abs(sample) for sample in pcm) < 6000:
        raise AssertionError("Normalized Armenian stream is still too quiet after PCM conversion")

    try:
        _stream_normalization_gain(0.0)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Digital silence must be rejected rather than amplified")
    failed_source = StreamingPCMSource(lambda _message: None)
    expected_error = RuntimeError("simulated Pocket TTS failure")
    failed_source.finish(expected_error)
    try:
        failed_source.read()
    except RuntimeError as exc:
        if expected_error.__str__() not in str(exc):
            raise AssertionError(f"Stream error detail was lost: {exc}") from exc
    else:
        raise AssertionError("Armenian stream source swallowed its synthesis error")

    print("PASS: Armenian PCM framing and stream-error propagation")


if __name__ == "__main__":
    main()
