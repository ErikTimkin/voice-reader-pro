import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import normalize_voice_key
from voice_reader.voice_profiles import VOICE_PRESETS


def main() -> None:
    if set(VOICE_PRESETS) != {"normal", "female", "cute_girl", "armenian"}:
        raise AssertionError(f"Expected default, female, Armenian and pop voices: {list(VOICE_PRESETS)}")
    assert normalize_voice_key("normal") == "normal"
    assert normalize_voice_key("female") == "female"
    assert normalize_voice_key("cute_girl") == "cute_girl"
    assert normalize_voice_key("armenian") == "armenian"
    assert normalize_voice_key("pop") == "cute_girl"
    # Old Pudge configs fall back to the regular male voice.
    assert normalize_voice_key("pudge") == "normal"
    assert VOICE_PRESETS["armenian"]["engine"] == "armenian"
    assert VOICE_PRESETS["female"]["speaker"] == "baya"
    assert VOICE_PRESETS["cute_girl"]["speaker"] == "xenia"

    page = (ROOT / "voice_reader" / "static" / "index.html").read_text(encoding="utf-8")
    required = [
        'data-voice="normal"',
        'data-voice="female"',
        'data-voice="cute_girl"',
        'data-voice="armenian"',
        'Обычный мужской',
        'Милая девушка',
        'Армянский акцент',
        'Молодой поп-голос',
        "event.key === 'Enter'",
        "!event.shiftKey",
        "JSON.stringify({text: text, voice: voice})",
        "-apple-system",
        "--page: #f5f5f7",
        "pendingRequests",
        "Отправить",
        "let selectedVoice = '__DEFAULT_VOICE__';",
        "card.dataset.voice === selectedVoice",
    ]
    for fragment in required:
        if fragment not in page:
            raise AssertionError(f"Web UI is missing required fragment: {fragment}")
    for retired in ('Пудж из Dota 2', 'data-voice="pudge"'):
        if retired in page:
            raise AssertionError(f"Retired voice still appears in web UI: {retired}")

    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    for fragment in ["#090d18", "Primary.TButton", "Журнал работы", "Voice Reader Pro", "rar$"]:
        if fragment not in app:
            raise AssertionError(f"Desktop dark theme is missing: {fragment}")

    core = (ROOT / "voice_reader" / "core.py").read_text(encoding="utf-8")
    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    if "LocalSileroTTS" not in core or "v5_6_ru.pt" not in app:
        raise AssertionError("The default and female Silero voices must remain installed")
    if "RATE_WINDOW" in core or "RATE_COUNT" in core or "def allowed(" in core:
        raise AssertionError("Server-side per-minute request throttling is still enabled")
    if "self.queue = asyncio.Queue()" not in core:
        raise AssertionError("The message queue must not have a small fixed capacity")
    if "self.queue.full()" in core:
        raise AssertionError("Requests should not be rejected because the old queue capacity was reached")

    print("Apple-style web UI, Enter/Shift+Enter, concurrent sends, and no rate limit passed.")


if __name__ == "__main__":
    main()
