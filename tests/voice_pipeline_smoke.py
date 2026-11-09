from pathlib import Path

import discord

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg.exe"
MP3 = ROOT / "tools" / "voice-pipeline-smoke.mp3"

def main() -> None:
    if not FFMPEG.is_file():
        raise SystemExit(f"FFmpeg not found: {FFMPEG}")
    if not MP3.is_file():
        raise SystemExit(f"MP3 fixture not found: {MP3}")

    # The PCM route requires the bundled libopus DLL, then discord.py encodes
    # 20 ms of 48 kHz stereo PCM into one Opus packet.
    encoder = discord.opus.Encoder(signal_type="voice")
    if not discord.opus.is_loaded():
        raise SystemExit("discord.py libopus did not load")

    source = discord.FFmpegPCMAudio(
        str(MP3),
        executable=str(FFMPEG),
        before_options="-nostdin",
        options="-af volume=1.5",
    )
    frames = 0
    total_pcm_bytes = 0
    try:
        while True:
            pcm = source.read()
            if not pcm:
                break
            if len(pcm) != discord.opus.Encoder.FRAME_SIZE:
                raise SystemExit(f"Unexpected PCM frame size: {len(pcm)}")
            encoded = encoder.encode(pcm, discord.opus.Encoder.SAMPLES_PER_FRAME)
            if not encoded:
                raise SystemExit("libopus returned an empty packet")
            frames += 1
            total_pcm_bytes += len(pcm)
    finally:
        source.cleanup()

    if frames < 20:
        raise SystemExit(f"Too few PCM frames decoded: {frames}")
    print(
        "PCM/Opus smoke test passed:",
        f"frames={frames}",
        f"pcm_bytes={total_pcm_bytes}",
        f"libopus_loaded={discord.opus.is_loaded()}",
    )

if __name__ == "__main__":
    main()
