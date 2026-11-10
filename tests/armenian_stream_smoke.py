import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from voice_reader.core import StreamingPCMSource


def main() -> None:
    source = StreamingPCMSource(lambda _message: None)
    source.push_mono_24k(np.sin(np.linspace(0, 30, 1920, dtype=np.float32)) * 0.2)
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
    print("PASS: Armenian 24 kHz chunks convert to Discord 48 kHz stereo PCM frames")


if __name__ == "__main__":
    main()
