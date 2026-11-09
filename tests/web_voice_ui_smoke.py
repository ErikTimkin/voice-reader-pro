import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import normalize_voice_key


def main() -> None:
    assert normalize_voice_key("normal") == "normal"
    assert normalize_voice_key("cute_girl") == "cute_girl"

    try:
        normalize_voice_key("pudge")
    except ValueError as exc:
        assert "Оригинальный голос Пуджа" in str(exc)
    else:
        raise AssertionError("The generic Silero low voice must not be advertised as authentic Pudge")

    page = (ROOT / "voice_reader" / "static" / "index.html").read_text(encoding="utf-8")
    required = [
        'data-voice="normal"',
        'data-voice="cute_girl"',
        'Пудж из Dota 2',
        "event.key==='Enter'",
        "!event.shiftKey",
        "JSON.stringify({text:text,voice:selectedVoice})",
        "radial-gradient",
    ]
    for fragment in required:
        if fragment not in page:
            raise AssertionError(f"Web UI is missing required fragment: {fragment}")

    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    for fragment in ["#090d18", "Primary.TButton", "Журнал работы", "Voice Reader Pro"]:
        if fragment not in app:
            raise AssertionError(f"Desktop dark theme is missing: {fragment}")

    print("Web voice selection, Enter/Shift+Enter, Pudge honesty and desktop dark theme passed.")


if __name__ == "__main__":
    main()
