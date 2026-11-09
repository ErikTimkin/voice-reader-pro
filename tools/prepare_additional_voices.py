from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlencode

import requests
from huggingface_hub import snapshot_download


ARMENIAN_DATASET = "ErikMkrtchyan/Hy-Generated-audio-data-with-cv20.0"
ARMENIAN_MODEL = "mnjoyan/pocket-tts-armenian"
TERA_MODEL = "TeraSpace/TeraTTSv2"


def download_tera(root: Path) -> None:
    target = root / "teratts"
    target.mkdir(parents=True, exist_ok=True)
    print("Downloading TeraTTSv2 distilled Russian male voice (ru_m5)…", flush=True)
    snapshot_download(
        repo_id=TERA_MODEL,
        repo_type="model",
        revision="main",
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
        "LICENSE",
        "LICENSE-OPENRAIL",
        "RUACCENT_NOTICE.txt",
    ]
    missing = [name for name in required if not (target / name).is_file()]
    if missing:
        raise RuntimeError(f"TeraTTSv2 download is missing required files: {missing}")
    print("TeraTTSv2 files verified.", flush=True)


def _dataset_config(session: requests.Session) -> str:
    url = "https://datasets-server.huggingface.co/splits?" + urlencode(
        {"dataset": ARMENIAN_DATASET}
    )
    response = session.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    for split in payload.get("splits", []):
        if split.get("split") == "train":
            return split["config"]
    raise RuntimeError(
        "The Common Voice Armenian dataset viewer did not expose the train split: "
        + json.dumps(payload)[:1200]
    )


def _is_male(value: object) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"female", "female_feminine", "f", "woman"}:
        return False
    return normalized in {"male", "male_masculine", "m", "man"} or normalized.startswith(
        "male_"
    )


def _audio_url(row: dict) -> str | None:
    audio = row.get("audio")
    if isinstance(audio, dict):
        return audio.get("src")
    if isinstance(audio, str) and audio.startswith("http"):
        return audio
    return None


def _convert_candidate(
    session: requests.Session, audio_url: str, ffmpeg: Path, target: Path
) -> float:
    with tempfile.TemporaryDirectory(prefix="armenian-reference-") as temporary:
        source = Path(temporary) / "source-audio"
        response = session.get(audio_url, timeout=(30, 180), stream=True)
        response.raise_for_status()
        with source.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)

        command = [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-t",
            "10",
            "-c:a",
            "pcm_s16le",
            str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError("FFmpeg could not convert the Armenian reference clip: " + result.stderr[-800:])

    with wave.open(str(target), "rb") as audio:
        return audio.getnframes() / float(audio.getframerate())


def download_armenian_reference(root: Path, ffmpeg: Path) -> None:
    target_dir = root / "armenian"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "armenian_reference.wav"
    if target.is_file() and target.stat().st_size > 10_000:
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "VoiceReaderPro-model-pack/1.0"})
    config = _dataset_config(session)
    print(f"Looking for a 5–10 second male Common Voice Armenian clip (config={config})…", flush=True)

    # The dataset viewer supports 100 rows per request. We only retain the anonymized
    # audio samples, never the speaker's name, client_id, or other identifying metadata.
    total_rows = None
    candidates = 0
    for offset in range(0, 9300, 100):
        url = "https://datasets-server.huggingface.co/rows?" + urlencode(
            {
                "dataset": ARMENIAN_DATASET,
                "config": config,
                "split": "train",
                "offset": offset,
                "length": 100,
            }
        )
        response = session.get(url, timeout=90)
        if response.status_code == 404 and offset == 0:
            raise RuntimeError("The dataset viewer returned 404 for the Armenian train split.")
        response.raise_for_status()
        payload = response.json()
        total_rows = payload.get("num_rows_total", total_rows)

        for wrapper in payload.get("rows", []):
            row = wrapper.get("row", {})
            if not _is_male(row.get("gender")):
                continue
            audio_url = _audio_url(row)
            if not audio_url:
                continue
            candidates += 1
            temporary_output = target_dir / "armenian_reference.candidate.wav"
            try:
                duration = _convert_candidate(session, audio_url, ffmpeg, temporary_output)
            except Exception as exc:
                temporary_output.unlink(missing_ok=True)
                print(f"Skipping an unreadable public dataset clip: {exc}", flush=True)
                continue
            if 5.0 <= duration <= 10.0:
                temporary_output.replace(target)
                print(
                    f"Selected anonymized male Armenian reference audio: {duration:.2f}s "
                    f"({candidates} candidate clips checked).",
                    flush=True,
                )
                return
            temporary_output.unlink(missing_ok=True)

        if total_rows and offset + 100 >= total_rows:
            break

    raise RuntimeError(
        f"No valid 5–10 second male Armenian reference clip found after checking {candidates} candidates."
    )


def prepare_armenian(root: Path, ffmpeg: Path) -> None:
    target = root / "armenian"
    print("Downloading the Armenian/Russian/English Pocket TTS fine-tune…", flush=True)
    snapshot_download(
        repo_id=ARMENIAN_MODEL,
        repo_type="model",
        revision="main",
        local_dir=str(target),
        allow_patterns=[
            "tri_v1/model.safetensors",
            "tri_v1/tokenizer_tri.model",
            "configs/hy_text.py",
        ],
    )

    weights = target / "tri_v1" / "model.safetensors"
    tokenizer = target / "tri_v1" / "tokenizer_tri.model"
    text_module = target / "configs" / "hy_text.py"
    for path in (weights, tokenizer, text_module):
        if not path.is_file() or path.stat().st_size < 100:
            raise RuntimeError(f"Armenian model file is missing or incomplete: {path}")

    import yaml
    import pocket_tts

    base_config = Path(pocket_tts.__file__).parent / "config" / "english_2026-09_24l.yaml"
    if not base_config.is_file():
        raise FileNotFoundError(f"Pocket TTS base config not found: {base_config}")
    config = yaml.safe_load(base_config.read_text(encoding="utf-8"))
    config["weights_path"] = str(weights.resolve())
    config.pop("weights_path_without_voice_cloning", None)
    lookup = config["flow_lm"]["lookup_table"]
    lookup["n_bins"] = 12000
    lookup["tokenizer"] = "sentencepiece"
    lookup["tokenizer_path"] = str(tokenizer.resolve())

    config_path = target / "armenian_tri.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    download_armenian_reference(root, ffmpeg)

    (target / "ARMENIAN_MODEL_NOTICE.txt").write_text(
        "Model: mnjoyan/pocket-tts-armenian (tri_v1; Armenian + Russian + English).\n"
        "License declared by the model publisher: Creative Commons Attribution 4.0 (CC BY 4.0).\n"
        "Attribution: mnjoyan, https://huggingface.co/mnjoyan/pocket-tts-armenian\n"
        "The packaged voice is conditioned on a short anonymized Common Voice Armenian train clip.\n",
        encoding="utf-8",
    )
    (target / "REFERENCE_NOTICE.txt").write_text(
        "Reference audio source: ErikMkrtchyan/Hy-Generated-audio-data-with-cv20.0, train split.\n"
        "Dataset card declares CC0 1.0. The reference is a public Common Voice 20.0 Armenian clip.\n"
        "VoiceReader Pro retains only the short audio crop; speaker IDs and personal metadata are not packaged.\n"
        "Dataset: https://huggingface.co/datasets/ErikMkrtchyan/Hy-Generated-audio-data-with-cv20.0\n",
        encoding="utf-8",
    )
    print("Armenian Pocket TTS model, Russian normalizer and reference clip verified.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    args = parser.parse_args()
    args.voices_dir.mkdir(parents=True, exist_ok=True)
    if not args.ffmpeg.is_file():
        raise FileNotFoundError(args.ffmpeg)

    download_tera(args.voices_dir)
    prepare_armenian(args.voices_dir, args.ffmpeg)


if __name__ == "__main__":
    main()
