# PyInstaller one-file Windows build. The workflow supplies tools/*.exe.
# Collect both DAVE's native Rust extension and discord.py's bundled libopus DLL.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
davey_datas, davey_binaries, davey_hiddenimports = collect_all("davey")
discord_datas, discord_binaries, discord_hiddenimports = collect_all("discord")

a = Analysis(
    [str(root / "voice_reader" / "app.py")],
    pathex=[str(root)],
    binaries=[
        (str(root / "tools" / "ffmpeg.exe"), "."),
        (str(root / "tools" / "cloudflared.exe"), "."),
    ] + davey_binaries + discord_binaries,
    datas=[
        (str(root / "voice_reader" / "static"), "voice_reader/static"),
    ] + davey_datas + discord_datas,
    hiddenimports=[
        "discord.opus",
        "discord.voice_client",
    ] + davey_hiddenimports + discord_hiddenimports,
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VoiceReaderPro",
    console=False,
    upx=False,
    onefile=True,
)
