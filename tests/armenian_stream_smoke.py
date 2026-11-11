import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from voice_reader.additional_tts import ArmenianAccentTTS, _normalize_tts_samples
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

    # Verify that a long utterance begins feeding Discord before Pocket TTS
    # finishes generating the complete message (the old implementation buffered
    # every chunk and only sent audio after the generator returned).
    class TrackingSource:
        def __init__(self, model):
            import threading
            self.stop_event = threading.Event()
            self.model = model
            self.pushes_before_generation_finished = 0
            self.total_pushes = 0
            self.errors = []

        def push_mono_24k(self, samples):
            self.total_pushes += 1
            if not self.model.finished:
                self.pushes_before_generation_finished += 1
            self.last_peak = max(self.last_peak if hasattr(self, "last_peak") else 0.0,
                                 float(np.max(np.abs(samples))))

        def finish(self, error=None):
            if error:
                self.errors.append(error)

    class StreamingPocketModel:
        sample_rate = 24000

        def __init__(self):
            self.finished = False

        def generate_audio_stream(self, _voice_state, _text, copy_state, stop):
            if not copy_state:
                raise AssertionError("Pocket TTS stream must use an isolated voice state")
            for _ in range(6):
                yield quiet_wave[:960]
            self.finished = True

    streaming_model = StreamingPocketModel()
    streaming_armenian = ArmenianAccentTTS(ROOT / "unused-armenian-model", lambda _message: None)
    streaming_armenian.model = streaming_model
    streaming_armenian.voice_state = object()
    tracking_source = TrackingSource(streaming_model)
    streaming_armenian.stream_to_source("Проверка быстрого начала армянской речи", tracking_source)
    if tracking_source.pushes_before_generation_finished < 1:
        raise AssertionError("Armenian stream buffered the whole message before sending its first audio chunk")
    if tracking_source.last_peak < 0.80:
        raise AssertionError(f"Streaming Armenian prefill was not normalized: {tracking_source.last_peak}")
    if tracking_source.errors:
        raise AssertionError(f"Streaming Armenian source reported an error: {tracking_source.errors}")

    class QuietPocketModel:
        sample_rate = 24000

        def generate_audio_stream(self, _voice_state, _text, copy_state, stop):
            if not copy_state:
                raise AssertionError("Pocket TTS stream must use an isolated voice state")
            yield quiet_wave[:960]
            yield quiet_wave[960:]

    armenian = ArmenianAccentTTS(ROOT / "unused-armenian-model", lambda _message: None)
    armenian.model = QuietPocketModel()  # Skip loading external model weights in CI.
    armenian.voice_state = object()
    streamed_source = StreamingPCMSource(lambda _message: None)
    armenian.stream_to_source("Проверка армянского голоса", streamed_source)
    streamed_frames = []
    while True:
        frame = streamed_source.read()
        if not frame:
            break
        if len(frame) != StreamingPCMSource.FRAME_BYTES:
            raise AssertionError("Real Armenian stream emitted an invalid Discord PCM frame")
        streamed_frames.append(frame)
    if not streamed_frames:
        raise AssertionError("Real Armenian stream emitted no Discord PCM frames")
    streamed_pcm = np.frombuffer(b"".join(streamed_frames), dtype=np.int16)
    streamed_peak = int(np.max(np.abs(streamed_pcm)))
    if streamed_peak < 27000:
        raise AssertionError(
            f"Real Armenian streaming path did not normalize quiet chunks: peak={streamed_peak}"
        )

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
        f"(raw_peak={raw_peak:.6f}, pcm_peak={int(np.max(np.abs(pcm)))}, "
        f"stream_peak={streamed_peak})"
    )


if __name__ == "__main__":
    main()
