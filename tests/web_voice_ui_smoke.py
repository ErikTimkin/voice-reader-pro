import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.core import normalize_voice_key
from voice_reader.voice_profiles import VOICE_PRESETS


def main() -> None:
    expected = {"normal", "female", "cute_girl", "armenian2", "armenian3", "armenian4", "jelly_bear", "cartoon", "villain"}
    if set(VOICE_PRESETS) != expected:
        raise AssertionError(f"Expected nine browser voice presets: {list(VOICE_PRESETS)}")
    for voice in VOICE_PRESETS:
        assert normalize_voice_key(voice) == voice
    assert normalize_voice_key("armenian") == "armenian2"
    assert normalize_voice_key("pop") == "cute_girl"
    assert normalize_voice_key("pudge") == "normal"
    assert VOICE_PRESETS["armenian2"]["speaker"] == "ru_safarhuja"
    assert VOICE_PRESETS["armenian3"]["speaker"] == "ru_eduard"
    assert VOICE_PRESETS["armenian4"]["speaker"] == "ru_marat"
    assert VOICE_PRESETS["jelly_bear"]["speaker"] == "aidar"
    assert VOICE_PRESETS["cartoon"]["speaker"] == "xenia"
    assert VOICE_PRESETS["villain"]["speaker"] == "aidar"
    assert "asetrate=57600" in VOICE_PRESETS["cartoon"]["ffmpeg_options"]
    assert "asetrate=39360" in VOICE_PRESETS["villain"]["ffmpeg_options"]

    page = (ROOT / "voice_reader" / "static" / "index.html").read_text(encoding="utf-8")
    for voice in expected:
        if f'data-voice="{voice}"' not in page:
            raise AssertionError(f"Missing browser voice card: {voice}")
    if 'data-voice="armenian"' in page or "Восточный мужской акцент" in page:
        raise AssertionError("Retired Pocket TTS Armenian voice is still visible")
    for fragment in ("Армянский 2.0", "Кавказский акцент", "Татарский оттенок",
                     "event.key === 'Enter'", "!event.shiftKey",
                     "localStorage.getItem('voiceReaderSelectedVoice')",
                     "localStorage.setItem('voiceReaderSelectedVoice', selectedVoice)"):
        if fragment not in page:
            raise AssertionError(f"Web UI is missing required fragment: {fragment}")

    app = (ROOT / "voice_reader" / "app.py").read_text(encoding="utf-8")
    for fragment in ("def _watch_service_status", "def _refresh_system_awake",
                     "SetThreadExecutionState", "self.loop.run_until_complete(self.run_async(*args))",
                     "Перезапускаю Discord и веб-сервер", "args=(token, guild, channel, 'normal', ffmpeg, cloudflared)",
                     "def copy_selected_log", "def clear_log"):
        if fragment not in app:
            raise AssertionError(f"Desktop runtime feature is missing: {fragment}")
    if "armenian_tri.yaml" in app or "args=(token, guild, channel, 'armenian'" in app:
        raise AssertionError("Desktop startup still depends on retired Pocket TTS")
    if app.count("self.log = tk.Text(") != 1:
        raise AssertionError("Desktop log widget must be created exactly once")

    core = (ROOT / "voice_reader" / "core.py").read_text(encoding="utf-8")
    if "self.armenian_tts" in core or "engine == \"armenian\"" in core:
        raise AssertionError("Retired Pocket TTS engine is still connected to the runtime")
    if "self.armenian2_tts" not in core or "LocalSileroTTS" not in core:
        raise AssertionError("Silero CIS and standard voices must remain available")
    if "RATE_WINDOW" in core or "RATE_COUNT" in core or "def allowed(" in core:
        raise AssertionError("Server-side per-minute request throttling is still enabled")
    if "self.queue = asyncio.Queue()" not in core or "self.queue.full()" in core:
        raise AssertionError("The message queue must remain unbounded")

    print("Nine browser voices, three eastern-accent CIS variants, selectable logs, keep-awake refresh, and service restart supervision passed.")


if __name__ == "__main__":
    main()
