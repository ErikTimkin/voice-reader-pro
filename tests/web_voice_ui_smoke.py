import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import normalize_voice_key
from voice_reader.voice_profiles import VOICE_PRESETS


def main() -> None:
    if set(VOICE_PRESETS) != {"armenian", "pop"}:
        raise AssertionError(f"Only Armenian and pop voices should remain: {list(VOICE_PRESETS)}")
    assert normalize_voice_key("armenian") == "armenian"
    assert normalize_voice_key("pop") == "pop"
    # Existing installations with old saved settings keep working after upgrade.
    assert normalize_voice_key("normal") == "armenian"
    assert normalize_voice_key("cute_girl") == "armenian"
    assert normalize_voice_key("pudge") == "armenian"
    assert VOICE_PRESETS["armenian"]["engine"] == "armenian"
    assert VOICE_PRESETS["pop"]["engine"] == "teratts"

    page = (ROOT / "voice_reader" / "static" / "index.html").read_text(encoding="utf-8")
    required = [
        'data-voice="armenian"',
        'data-voice="pop"',
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
    for retired in ('Пудж из Dota 2', 'Обычный мужской', 'Милая девушка', 'data-voice="normal"', 'data-voice="cute_girl"'):
        if retired in page:
            raise AssertionError(f"Retired voice still appears in web UI: {retired}")

    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    for fragment in ["#090d18", "Primary.TButton", "Журнал работы", "Voice Reader Pro", "rar$"]:
        if fragment not in app:
            raise AssertionError(f"Desktop dark theme is missing: {fragment}")

    core = (ROOT / "voice_reader" / "core.py").read_text(encoding="utf-8")
    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    if "LocalSileroTTS" in core or "v5_6_ru.pt" in app:
        raise AssertionError("The retired Silero voice pack must not be required")
    if "RATE_WINDOW" in core or "RATE_COUNT" in core or "def allowed(" in core:
        raise AssertionError("Server-side per-minute request throttling is still enabled")
    if "self.queue = asyncio.Queue()" not in core:
        raise AssertionError("The message queue must not have a small fixed capacity")
    if "self.queue.full()" in core:
        raise AssertionError("Requests should not be rejected because the old queue capacity was reached")

    print("Apple-style web UI, Enter/Shift+Enter, concurrent sends, and no rate limit passed.")


if __name__ == "__main__":
    main()
