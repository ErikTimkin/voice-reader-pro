# PyInstaller one-file Windows build. The workflow supplies tools/*.exe.
# The local Silero model remains beside the EXE in voices/v5_6_ru.pt.
# Collect DAVE, discord.py/libopus, PyTorch and NumPy native libraries.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
davey_datas, davey_binaries, davey_hiddenimports = collect_all("davey")
discord_datas, discord_binaries, discord_hiddenimports = collect_all("discord")
torch_datas, torch_binaries, torch_hiddenimports = collect_all("torch")
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all("numpy")

a = Analysis(
    [str(root / "voice_reader" / "app.py")],
    pathex=[str(root)],
    binaries=[
        (str(root / "tools" / "ffmpeg.exe"), "."),
        (str(root / "tools" / "cloudflared.exe"), "."),
    ] + davey_binaries + discord_binaries + torch_binaries + numpy_binaries,
    datas=[
        (str(root / "voice_reader" / "static"), "voice_reader/static"),
    ] + davey_datas + discord_datas + torch_datas + numpy_datas,
    hiddenimports=[
        "discord.opus",
        "discord.voice_client",
        "torch.package",
        "torch._C",
        "numpy",
    ] + davey_hiddenimports + discord_hiddenimports + torch_hiddenimports + numpy_hiddenimports,
    hookspath=[],
    excludes=["torch.distributed", "torch.testing", "torch.utils.tensorboard"],
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
