import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import BlockingMP3Stream, resolve_voice_profile


def main() -> None:
    # A small Edge TTS audio packet must be released immediately even when
    # FFmpeg asks for 8192 bytes; do not wait for a full buffer.
    stream = BlockingMP3Stream()
    first_chunk = b"first-audio-chunk"
    stream.feed(first_chunk)
    actual = stream.read(8192)
    if actual != first_chunk:
        raise AssertionError(f"Streaming reader buffered the first chunk: {actual!r}")

    stream.feed(b"second")
    stream.finish()
    if stream.read(8192) != b"second":
        raise AssertionError("Streaming reader did not preserve the next chunk")
    if stream.read(8192) != b"":
        raise AssertionError("Streaming reader did not return EOF after finish")

    pudge = resolve_voice_profile("pudge")
    if pudge["voice"] != "ru-RU-DmitryNeural" or pudge["pitch"] != "-18Hz":
        raise AssertionError(f"Unexpected Pudge voice preset: {pudge}")

    cute = resolve_voice_profile("cute_girl")
    if cute["voice"] != "ru-RU-SvetlanaNeural" or cute["pitch"] != "+10Hz":
        raise AssertionError(f"Unexpected cute-girl voice preset: {cute}")

    dariya = resolve_voice_profile("dariya")
    if dariya["voice"] != "ru-RU-DariyaNeural":
        raise AssertionError(f"Unexpected Dariya voice preset: {dariya}")

    legacy = resolve_voice_profile("ru-RU-DmitryNeural")
    if legacy["voice"] != "ru-RU-DmitryNeural":
        raise AssertionError("Legacy saved Dmitry setting is not supported")

    print("Low-latency stream buffer and Russian voice preset tests passed.")


if __name__ == "__main__":
    main()
