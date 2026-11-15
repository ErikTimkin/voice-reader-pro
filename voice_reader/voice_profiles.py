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
        "speaker": "aidar",
        # Deep, rounded bear timbre.
        "ffmpeg_options": "-af asetrate=42240,aresample=48000,atempo=1.136,bass=g=5:f=150,lowpass=f=5200,acompressor=threshold=0.12:ratio=2.2:attack=8:release=90,volume=1.2",
    },
    "cartoon": {
        "label": "Мультяшный",
        "engine": "silero",
        "speaker": "xenia",
        # Raise pitch by 20% while restoring the original duration.
        "ffmpeg_options": "-af asetrate=57600,aresample=48000,atempo=0.833333,highpass=f=140,treble=g=2:f=4200,acompressor=threshold=0.14:ratio=2:attack=8:release=90,volume=1.15",
    },
    "villain": {
        "label": "Злодей",
        "engine": "silero",
        "speaker": "aidar",
        # Lower pitch by 18%, restore duration, and add a controlled dark low end.
        "ffmpeg_options": "-af asetrate=39360,aresample=48000,atempo=1.219512,bass=g=7:f=110,lowpass=f=4300,acompressor=threshold=0.13:ratio=2.4:attack=10:release=110,volume=1.2",
    },
    "armenian2": {
        "label": "Армянский 2.0 · таджикский оттенок",
        "engine": "silero_cis",
        "speaker": "ru_safarhuja",
        "ffmpeg_options": "-af volume=1.1",
    },
    "armenian3": {
        "label": "Кавказский акцент",
        "engine": "silero_cis",
        "speaker": "ru_eduard",
        "ffmpeg_options": "-af volume=1.1",
    },
    "armenian4": {
        "label": "Татарский оттенок",
        "engine": "silero_cis",
        "speaker": "ru_marat",
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
    # Armenian 2.0/3/4 remain available as independent Silero CIS presets.
    "armenian": "armenian2",
}


def resolve_voice_profile(selection: str | None) -> dict:
    key = LEGACY_VOICE_IDS.get(selection or "", selection or "normal")
    return dict(VOICE_PRESETS.get(key, VOICE_PRESETS["normal"]))
