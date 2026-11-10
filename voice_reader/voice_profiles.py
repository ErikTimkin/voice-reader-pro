"""Voice presets for Voice Reader Pro."""
from __future__ import annotations

VOICE_PRESETS = {
    "normal": {
        "label": "Обычный мужской",
        "engine": "silero",
        "speaker": "aidar",
        "ffmpeg_options": "-af volume=1.15",
    },
    "cute_girl": {
        "label": "Милая девушка",
        "engine": "silero",
        "speaker": "xenia",
        "ffmpeg_options": "-af volume=1.15",
    },
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

# Keep old saved settings usable. The removed Pudge entry falls back to default male.
LEGACY_VOICE_IDS = {
    "dmitry": "normal",
    "ru-RU-DmitryNeural": "normal",
    "pudge": "normal",
    "svetlana": "cute_girl",
    "ru-RU-SvetlanaNeural": "cute_girl",
    "dariya": "cute_girl",
    "ru-RU-DariyaNeural": "cute_girl",
}


def resolve_voice_profile(selection: str | None) -> dict:
    key = LEGACY_VOICE_IDS.get(selection or "", selection or "normal")
    return dict(VOICE_PRESETS.get(key, VOICE_PRESETS["normal"]))
