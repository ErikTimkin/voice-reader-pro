import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.local_tts import resolve_voice_profile, VOICE_PRESETS


def main() -> None:
    expected = {
        "normal": "aidar",
        "pudge": "eugene",
        "cute_girl": "xenia",
    }
    if set(VOICE_PRESETS) != set(expected):
        raise AssertionError(f"Expected exactly 3 voice presets, got: {list(VOICE_PRESETS)}")

    for preset, speaker in expected.items():
        profile = resolve_voice_profile(preset)
        if profile["speaker"] != speaker:
            raise AssertionError(f"{preset}: expected {speaker}, got {profile}")

    legacy = resolve_voice_profile("ru-RU-DmitryNeural")
    if legacy["speaker"] != "aidar":
        raise AssertionError("Legacy saved Dmitry profile was not mapped to local normal voice")

    print("Exactly three local Russian voice presets passed.")
    

if __name__ == "__main__":
    main()
