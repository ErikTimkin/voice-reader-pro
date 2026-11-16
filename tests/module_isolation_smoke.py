"""Guard the architectural boundary between the two runtime modes."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def main() -> None:
    text_modules = {
        "voice_reader.app",
        "voice_reader.core",
        "voice_reader.local_tts",
        "voice_reader.voice_profiles",
    }
    live_modules = {
        "voice_reader.live_audio",
        "voice_reader.live_voice_ui",
    }
    live_imports = imports(ROOT / "voice_reader" / "live_audio.py") | imports(
        ROOT / "voice_reader" / "live_voice_ui.py"
    )
    app_imports = imports(ROOT / "voice_reader" / "app.py")
    assert not (live_imports & text_modules), (
        "Live voice code must not import text bot internals: "
        + ", ".join(sorted(live_imports & text_modules))
    )
    assert not (app_imports & live_modules), (
        "Text bot must not import live voice modules: "
        + ", ".join(sorted(app_imports & live_modules))
    )
    assert (ROOT / "launcher.py").is_file()
    assert (ROOT / "voice_reader" / "live_app.py").is_file()
    print("PASS: text and live voice module import boundaries are isolated")


if __name__ == "__main__":
    main()
