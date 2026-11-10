from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


TERA_MODEL = "TeraSpace/TeraTTSv2"


def download_tera(root: Path) -> None:
    target = root / "teratts"
    target.mkdir(parents=True, exist_ok=True)
    revision = HfApi().model_info(TERA_MODEL).sha
    print(
        f"Downloading pinned TeraTTSv2 revision {revision} "
        "(Russian male and foreign-accent male styles)…",
        flush=True,
    )
    snapshot_download(
        repo_id=TERA_MODEL,
        repo_type="model",
        revision=revision,
        local_dir=str(target),
        allow_patterns=[
            "teratts.py",
            "teratts_ruaccent.py",
            "configuration_teratts.py",
            "modeling_teratts.py",
            "config.json",
            "unicode_indexer.json",
            "models/text_encoder.onnx",
            "models/duration_predictor.onnx",
            "models/sampler_distilled_cfg3_8step.onnx",
            "models/vocoder.onnx",
            "ruaccent/**",
            "styles/ru_m5/**",
            "styles/eng_m4/**",
            "LICENSE",
            "LICENSE-OPENRAIL",
            "RUACCENT_NOTICE.txt",
        ],
    )
    required = [
        "teratts.py",
        "teratts_ruaccent.py",
        "unicode_indexer.json",
        "models/text_encoder.onnx",
        "models/duration_predictor.onnx",
        "models/sampler_distilled_cfg3_8step.onnx",
        "models/vocoder.onnx",
        "styles/ru_m5/style_ttl.npy",
        "styles/ru_m5/style_dp.npy",
        "styles/eng_m4/style_ttl.npy",
        "styles/eng_m4/style_dp.npy",
        "LICENSE",
        "LICENSE-OPENRAIL",
        "RUACCENT_NOTICE.txt",
    ]
    missing = [name for name in required if not (target / name).is_file()]
    if missing:
        raise RuntimeError(f"TeraTTSv2 download is missing required files: {missing}")
    print("TeraTTSv2 verified: ru_m5 and eng_m4 styles are both installed.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    args = parser.parse_args()
    args.voices_dir.mkdir(parents=True, exist_ok=True)
    if not args.ffmpeg.is_file():
        raise FileNotFoundError(args.ffmpeg)
    download_tera(args.voices_dir)


if __name__ == "__main__":
    main()
