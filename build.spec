# PyInstaller one-file Windows build. The workflow supplies tools/*.exe.
# davey is a native Rust extension and must be collected explicitly for DAVE voice encryption.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
davey_datas, davey_binaries, davey_hiddenimports = collect_all("davey")

a = Analysis(
    [str(root / "voice_reader" / "app.py")],
    pathex=[str(root)],
    binaries=[
        (str(root / "tools" / "ffmpeg.exe"), "."),
        (str(root / "tools" / "cloudflared.exe"), "."),
    ] + davey_binaries,
    datas=[
        (str(root / "voice_reader" / "static"), "voice_reader/static"),
    ] + davey_datas,
    hiddenimports=[
        "discord.opus",
        "discord.voice_client",
    ] + davey_hiddenimports,
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
