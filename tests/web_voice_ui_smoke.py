import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import normalize_voice_key


def main() -> None:
    assert normalize_voice_key("normal") == "normal"
    assert normalize_voice_key("cute_girl") == "cute_girl"
    assert normalize_voice_key("armenian") == "armenian"
    assert normalize_voice_key("pop") == "pop"

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
        'data-voice="armenian"',
        'data-voice="pop"',
        'Армянский акцент',
        'Молодой поп-голос',
        'Пудж из Dota 2',
        "event.key === 'Enter'",
        "!event.shiftKey",
        "JSON.stringify({text: text, voice: voice})",
        "-apple-system",
        "--page: #f5f5f7",
        "pendingRequests",
        "Отправить",
    ]
    for fragment in required:
        if fragment not in page:
            raise AssertionError(f"Web UI is missing required fragment: {fragment}")

    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    for fragment in ["#090d18", "Primary.TButton", "Журнал работы", "Voice Reader Pro"]:
        if fragment not in app:
            raise AssertionError(f"Desktop dark theme is missing: {fragment}")

    core = (ROOT / "voice_reader" / "core.py").read_text(encoding="utf-8")
    if "RATE_WINDOW" in core or "RATE_COUNT" in core or "def allowed(" in core:
        raise AssertionError("Server-side per-minute request throttling is still enabled")
    if "self.queue = asyncio.Queue()" not in core:
        raise AssertionError("The message queue must not have a small fixed capacity")
    if "self.queue.full()" in core:
        raise AssertionError("Requests should not be rejected because the old queue capacity was reached")

    print("Apple-style web UI, Enter/Shift+Enter, concurrent sends, and no rate limit passed.")


if __name__ == "__main__":
    main()
