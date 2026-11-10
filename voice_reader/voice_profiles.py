"""Voice presets for Voice Reader Pro."""
from __future__ import annotations

VOICE_PRESETS = {
    "normal": {
        "label": "Обычный мужской",
        "engine": "silero",
        "speaker": "aidar",
        "ffmpeg_options": "-af volume=1.15",
    },
    "female": {
        "label": "Обычный женский",
        "engine": "silero",
        "speaker": "baya",
        "ffmpeg_options": "-af volume=1.15",
    },
    "cute_girl": {
        "label": "Милый голос",
        "engine": "silero",
        "speaker": "xenia",
        "ffmpeg_options": "-af volume=1.15",
    },
    "jelly_bear": {
        "label": "Желейный медведь",
        "engine": "silero",
        "speaker": "xenia",
        # Bright, high-pitched cartoon tone without cloning a real performer.
        "ffmpeg_options": "-af asetrate=57120,aresample=48000,atempo=0.84,volume=1.15",
    },
    "armenian": {
        "label": "Армянский акцент",
        "engine": "armenian",
        "ffmpeg_options": "-af volume=1.1",
    },
}

VOICE_PRESET_LABELS = {key: value["label"] for key, value in VOICE_PRESETS.items()}
VOICE_LABEL_TO_PRESET = {value["label"]: key for key, value in VOICE_PRESETS.items()}

# Keep old saved settings usable. The removed Pudge/pop entries fall back to
# the closest available voice instead of breaking saved configurations.
LEGACY_VOICE_IDS = {
    "dmitry": "normal",
    "ru-RU-DmitryNeural": "normal",
    "pudge": "normal",
    "pop": "cute_girl",
    "svetlana": "female",
    "ru-RU-SvetlanaNeural": "female",
    "dariya": "female",
    "ru-RU-DariyaNeural": "female",
}


def resolve_voice_profile(selection: str | None) -> dict:
    key = LEGACY_VOICE_IDS.get(selection or "", selection or "normal")
    return dict(VOICE_PRESETS.get(key, VOICE_PRESETS["normal"]))
