# PyInstaller onedir Windows build.
# The local Silero model is distributed alongside the app in voices/.
# A folder build avoids extracting the entire PyTorch runtime to a temp
# directory on every launch, while the user still starts VoiceReaderPro.exe.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
davey_datas, davey_binaries, davey_hiddenimports = collect_all("davey")
discord_datas, discord_binaries, discord_hiddenimports = collect_all("discord")
torch_datas, torch_binaries, torch_hiddenimports = collect_all("torch")
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all("numpy")
pocket_datas, pocket_binaries, pocket_hiddenimports = collect_all("pocket_tts")
onnx_datas, onnx_binaries, onnx_hiddenimports = collect_all("onnxruntime")
sentencepiece_datas, sentencepiece_binaries, sentencepiece_hiddenimports = collect_all("sentencepiece")
yaml_datas, yaml_binaries, yaml_hiddenimports = collect_all("yaml")
scipy_datas, scipy_binaries, scipy_hiddenimports = collect_all("scipy")
safetensors_datas, safetensors_binaries, safetensors_hiddenimports = collect_all("safetensors")
tokenizers_datas, tokenizers_binaries, tokenizers_hiddenimports = collect_all("tokenizers")
huggingface_datas, huggingface_binaries, huggingface_hiddenimports = collect_all("huggingface_hub")
pydantic_datas, pydantic_binaries, pydantic_hiddenimports = collect_all("pydantic")

a = Analysis(
    [str(root / "voice_reader" / "app.py")],
    pathex=[str(root)],
    binaries=[
        (str(root / "tools" / "ffmpeg.exe"), "."),
        (str(root / "tools" / "cloudflared.exe"), "."),
    ] + davey_binaries + discord_binaries + torch_binaries + numpy_binaries
      + pocket_binaries + onnx_binaries + sentencepiece_binaries + yaml_binaries
      + scipy_binaries + safetensors_binaries + tokenizers_binaries
      + huggingface_binaries + pydantic_binaries,
    datas=[
        (str(root / "voice_reader" / "static"), "voice_reader/static"),
    ] + davey_datas + discord_datas + torch_datas + numpy_datas
      + pocket_datas + onnx_datas + sentencepiece_datas + yaml_datas
      + scipy_datas + safetensors_datas + tokenizers_datas
      + huggingface_datas + pydantic_datas,
    hiddenimports=[
        "discord.opus",
        "discord.voice_client",
        "torch.package",
        "torch._C",
        "numpy",
    ] + davey_hiddenimports + discord_hiddenimports + torch_hiddenimports + numpy_hiddenimports
      + pocket_hiddenimports + onnx_hiddenimports + sentencepiece_hiddenimports + yaml_hiddenimports
      + scipy_hiddenimports + safetensors_hiddenimports + tokenizers_hiddenimports
      + huggingface_hiddenimports + pydantic_hiddenimports,
    hookspath=[],
    excludes=["torch.distributed", "torch.testing", "torch.utils.tensorboard"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceReaderPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoiceReaderPro",
)
