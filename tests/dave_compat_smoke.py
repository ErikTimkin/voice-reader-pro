import inspect
from importlib.metadata import version

import discord
import davey
from discord.gateway import DiscordVoiceWebSocket
from discord.voice_client import VoiceClient
from discord.voice_state import VoiceConnectionState


def require_source(obj, fragments, label):
    source = inspect.getsource(obj)
    for fragment in fragments:
        if fragment not in source:
            raise AssertionError(f"{label} is missing expected DAVE support: {fragment}")


def main():
    discord_version = version("discord.py")
    if not discord_version.startswith("2.8.0a5438+g283cafbd"):
        raise AssertionError(f"Unexpected discord.py build (expected pinned DAVE commit): {discord_version}")
    if version("davey") != "0.2.0":
        raise AssertionError(f"Unexpected davey version: {version('davey')}")
    if version("PyNaCl") != "1.6.0":
        raise AssertionError(f"Unexpected PyNaCl version: {version('PyNaCl')}")

    require_source(
        VoiceConnectionState.__init__,
        ["connected_user_ids", "dave_downgraded"],
        "VoiceConnectionState.__init__",
    )
    require_source(
        VoiceConnectionState.reinit_dave_session,
        ["dave_pending_transitions.clear", "get_serialized_key_package"],
        "VoiceConnectionState.reinit_dave_session",
    )
    require_source(
        VoiceConnectionState._execute_transition,
        ["execute_transition", "dave_pending_transitions.pop"],
        "VoiceConnectionState._execute_transition",
    )
    require_source(
        DiscordVoiceWebSocket.received_message,
        ["CLIENTS_CONNECT", "CLIENT_DISCONNECT", "prepare_transition"],
        "DiscordVoiceWebSocket.received_message",
    )
    require_source(
        DiscordVoiceWebSocket.received_binary_message,
        ["connected_user_ids", "process_proposals", "process_welcome", "prepare_transition"],
        "DiscordVoiceWebSocket.received_binary_message",
    )
    require_source(
        VoiceClient._get_voice_packet,
        ["dave_session.can_encrypt", "encrypt_opus"],
        "VoiceClient._get_voice_packet",
    )

    # Ensure the native Opus encoder is available and accepts a real 20 ms frame.
    encoder = discord.opus.Encoder(signal_type="voice")
    encoded = encoder.encode(bytes(discord.opus.Encoder.FRAME_SIZE), discord.opus.Encoder.SAMPLES_PER_FRAME)
    if not encoded:
        raise AssertionError("libopus returned an empty encoded packet")

    print(
        "DAVE compatibility smoke test passed:",
        f"discord.py={discord_version}",
        f"davey={version('davey')}",
        f"PyNaCl={version('PyNaCl')}",
        f"libopus_loaded={discord.opus.is_loaded()}",
        f"opus_packet_bytes={len(encoded)}",
    )


if __name__ == "__main__":
    main()
