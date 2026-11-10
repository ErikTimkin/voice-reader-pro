import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.local_tts import resolve_voice_profile, VOICE_PRESETS


def main() -> None:
    expected = {
        "normal": ("silero", "aidar"),
        "pudge": ("silero", "eugene"),
        "cute_girl": ("silero", "xenia"),
        "accent": ("teratts", "eng_m4"),
        "pop": ("teratts", "ru_m5"),
    }
    if set(VOICE_PRESETS) != set(expected):
        raise AssertionError(f"Expected exactly 5 voice presets, got: {list(VOICE_PRESETS)}")

    for preset, (engine, speaker) in expected.items():
        profile = resolve_voice_profile(preset)
        if profile.get("engine") != engine or profile.get("speaker") != speaker:
            raise AssertionError(f"{preset}: expected {(engine, speaker)}, got {profile}")

    legacy = resolve_voice_profile("ru-RU-DmitryNeural")
    if legacy["speaker"] != "aidar":
        raise AssertionError("Legacy saved Dmitry profile was not mapped to local normal voice")

    print("Five local and cross-language voice presets passed.")
    

if __name__ == "__main__":
    main()
