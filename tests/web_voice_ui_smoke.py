import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import normalize_voice_key
from voice_reader.voice_profiles import VOICE_PRESETS


def main() -> None:
    if set(VOICE_PRESETS) != {"normal", "female", "cute_girl", "armenian", "jelly_bear"}:
        raise AssertionError(f"Expected five browser voice presets: {list(VOICE_PRESETS)}")
    for voice in VOICE_PRESETS:
        assert normalize_voice_key(voice) == voice
    assert VOICE_PRESETS["jelly_bear"]["speaker"] == "xenia"
    assert "asetrate=57120" in VOICE_PRESETS["jelly_bear"]["ffmpeg_options"]
    assert normalize_voice_key("pop") == "cute_girl"
    assert normalize_voice_key("pudge") == "normal"
    assert VOICE_PRESETS["armenian"]["engine"] == "armenian"
    assert VOICE_PRESETS["female"]["speaker"] == "baya"
    assert VOICE_PRESETS["cute_girl"]["speaker"] == "xenia"

    page = (ROOT / "voice_reader" / "static" / "index.html").read_text(encoding="utf-8")
    required = [
        'data-voice="normal"', 'data-voice="female"', 'data-voice="cute_girl"',
        'data-voice="armenian"', 'data-voice="jelly_bear"', "Желейный медведь",
        'Обычный мужской', 'Обычный женский', 'Армянский акцент', 'Милый голос',
        "event.key === 'Enter'", "!event.shiftKey",
        "JSON.stringify({text: text, voice: voice})", "-apple-system",
        "--page: #f5f5f7", "pendingRequests", "Отправить",
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
    for fragment in ["#090d18", "Primary.TButton", "Журнал работы", "Voice Reader Pro", "StatusCard.TFrame", "def _watch_service_status", "Работает · 127.0.0.1:8765",
                     "rar$", "def copy_selected_log", "def clear_log",
                     "self.log.bind('<Key>', self.protect_log)",
                     "self.log.bind('<Button-3>', self.show_log_menu)"]:
        if fragment not in app:
            raise AssertionError(f"Desktop UI feature is missing: {fragment}")
    if "'voice'" in app or "ГОЛОС ПО УМОЛЧАНИЮ" in app or "VOICE_PRESET_LABELS" in app:
        raise AssertionError("Voice selection must be available only in the browser UI")
    if app.count("self.log = tk.Text(") != 1:
        raise AssertionError("Desktop log widget must be created exactly once")
    if "voice_preset" in app:
        raise AssertionError("Desktop startup must use the browser-selected voice only")
    if "args=(token, guild, channel, 'normal', ffmpeg, cloudflared)" not in app:
        raise AssertionError("Desktop service must start with a valid default voice argument")
    if "self.log = tk.Text(\n            log_body," not in app:
        raise AssertionError("Log Text widget must be created inside its actual parent frame")
    if "self.log.pack(in_=log_body" in app:
        raise AssertionError("Log Text widget must not be packed into a descendant frame")
    log_widget = app.split("self.log = tk.Text(", 1)[1].split("        )", 1)[0]
    if "state='disabled'" in log_widget or "state='normal'" not in log_widget:
        raise AssertionError("Log Text widget must remain selectable for copying")

    core = (ROOT / "voice_reader" / "core.py").read_text(encoding="utf-8")
    if "LocalSileroTTS" not in core or "v5_6_ru.pt" not in app:
        raise AssertionError("The default and female Silero voices must remain installed")
    if "RATE_WINDOW" in core or "RATE_COUNT" in core or "def allowed(" in core:
        raise AssertionError("Server-side per-minute request throttling is still enabled")
    if "self.queue = asyncio.Queue()" not in core or "self.queue.full()" in core:
        raise AssertionError("The message queue must not reject requests due to a fixed capacity")

    print("Five browser voice presets, selectable/copyable desktop logs, and desktop UI passed.")


if __name__ == "__main__":
    main()
