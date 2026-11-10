"""The two offline voices kept in the compact build."""
from __future__ import annotations

VOICE_PRESETS = {
    "armenian": {
        "label": "Армянский акцент",
        "engine": "armenian",
        "ffmpeg_options": "-af volume=1.1",
    },
    "pop": {
        "label": "Молодой поп-голос",
        "engine": "teratts",
        "speaker": "ru_m5",
        "ffmpeg_options": "-af volume=1.1",
    },
}

VOICE_PRESET_LABELS = {key: value["label"] for key, value in VOICE_PRESETS.items()}
VOICE_LABEL_TO_PRESET = {value["label"]: key for key, value in VOICE_PRESETS.items()}

# Older config files may still contain these presets. Map them to the new default
# instead of failing when somebody upgrades from an older archive.
LEGACY_VOICE_IDS = {
    "normal": "armenian",
    "dmitry": "armenian",
    "ru-RU-DmitryNeural": "armenian",
    "pudge": "armenian",
    "cute_girl": "armenian",
    "svetlana": "armenian",
    "ru-RU-SvetlanaNeural": "armenian",
    "dariya": "armenian",
    "ru-RU-DariyaNeural": "armenian",
}


def resolve_voice_profile(selection: str | None) -> dict:
    key = LEGACY_VOICE_IDS.get(selection or "", selection or "armenian")
    return dict(VOICE_PRESETS.get(key, VOICE_PRESETS["armenian"]))
