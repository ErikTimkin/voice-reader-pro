# PyInstaller one-file Windows build. The workflow supplies tools/*.exe.
from pathlib import Path
root = Path(SPECPATH)
a = Analysis([str(root / 'voice_reader' / 'app.py')], pathex=[str(root)], binaries=[(str(root/'tools'/'ffmpeg.exe'), '.'), (str(root/'tools'/'cloudflared.exe'), '.')], datas=[(str(root/'voice_reader'/'static'), 'voice_reader/static')], hiddenimports=['discord.opus', 'discord.voice_client'], hookspath=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='VoiceReaderPro', console=False, upx=False, onefile=True)
