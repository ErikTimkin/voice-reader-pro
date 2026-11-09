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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from huggingface_hub import HfApi, snapshot_download


ARMENIAN_DATASET = "ErikMkrtchyan/Hy-Generated-audio-data-2"
ARMENIAN_MODEL = "mnjoyan/pocket-tts-armenian"
TERA_MODEL = "TeraSpace/TeraTTSv2"


def download_tera(root: Path) -> None:
    target = root / "teratts"
    target.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    revision = api.model_info(TERA_MODEL).sha
    print(f"Downloading pinned TeraTTSv2 revision {revision} (Russian male voice ru_m5)…", flush=True)
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


def _dataset_config(session: requests.Session, target_split: str) -> str:
    url = "https://datasets-server.huggingface.co/splits?" + urlencode(
        {"dataset": ARMENIAN_DATASET}
    )
    response = session.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    for split in payload.get("splits", []):
        if split.get("split") == target_split:
            return split["config"]
    raise RuntimeError(
        f"The synthetic Armenian dataset viewer did not expose the {target_split!r} split: "
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
    session: requests.Session,
    audio_url: str,
    ffmpeg: Path,
    temporary_dir: Path,
    index: int,
) -> tuple[Path, float]:
    source = temporary_dir / f"source-{index}"
    output_path = temporary_dir / f"clip-{index}.wav"
    response = session.get(audio_url, timeout=(30, 120), stream=True)
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
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not output_path.is_file():
        raise RuntimeError(
            "FFmpeg could not convert the Armenian reference clip: " + result.stderr[-800:]
        )
    with wave.open(str(output_path), "rb") as audio:
        duration = audio.getnframes() / float(audio.getframerate())
    return output_path, duration


def download_armenian_reference(root: Path, ffmpeg: Path) -> None:
    target_dir = root / "armenian"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "armenian_reference.wav"
    if target.is_file() and target.stat().st_size > 10_000:
        return

    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "VoiceReaderPro-model-pack/1.0"})

    split_name = "generated"
    config = _dataset_config(session, split_name)
    print(
        f"Looking for a 5–10 second synthetic male Armenian voice sample "
        f"(config={config}, split={split_name})…",
        flush=True,
    )

    total_rows = None
    male_rows = 0
    audio_candidates = 0
    clip_index = 0
    voice_clips: dict[str, list[tuple[Path, float]]] = {}

    with tempfile.TemporaryDirectory(prefix="armenian-reference-batch-") as temp_name:
        temporary_dir = Path(temp_name)

        for offset in range(0, 10_000, 100):
            url = "https://datasets-server.huggingface.co/rows?" + urlencode(
                {
                    "dataset": ARMENIAN_DATASET,
                    "config": config,
                    "split": split_name,
                    "offset": offset,
                    "length": 100,
                }
            )
            try:
                response = session.get(url, timeout=45)
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                print(
                    f"Dataset viewer failed at offset {offset}; skipping this page after retries: {exc}",
                    flush=True,
                )
                continue

            total_rows = payload.get("num_rows_total", total_rows)
            rows = payload.get("rows", [])
            page_male_rows = 0

            for wrapper in rows:
                row = wrapper.get("row", {})
                if not _is_male(row.get("gender")):
                    continue
                page_male_rows += 1
                male_rows += 1
                audio_url = _audio_url(row)
                if not audio_url:
                    continue

                audio_candidates += 1
                clip_index += 1
                try:
                    clip_path, duration = _convert_candidate(
                        session, audio_url, ffmpeg, temporary_dir, clip_index
                    )
                except Exception as exc:
                    print(f"Skipping an unreadable synthetic audio clip: {exc}", flush=True)
                    continue

                # client_id is used only in memory to join clips from the same
                # synthetic voice. It is never written to the package or logs.
                voice_id = str(row.get("client_id") or f"single-clip-{clip_index}")
                voice_clips.setdefault(voice_id, []).append((clip_path, duration))

                if 5.0 <= duration <= 10.0:
                    shutil.copy2(clip_path, target)
                    print(
                        f"Selected one synthetic male Armenian reference clip: {duration:.2f}s.",
                        flush=True,
                    )
                    return

                combined_duration = sum(item[1] for item in voice_clips[voice_id])
                if combined_duration >= 5.0:
                    list_file = temporary_dir / "reference-list.txt"
                    entries = []
                    for path, _duration in voice_clips[voice_id]:
                        escaped = str(path.resolve()).replace("'", "'\\''")
                        entries.append(f"file '{escaped}'")
                    list_file.write_text("\\n".join(entries) + "\\n", encoding="utf-8")

                    concat_command = [
                        str(ffmpeg),
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(list_file),
                        "-t",
                        "10",
                        "-ac",
                        "1",
                        "-ar",
                        "24000",
                        "-c:a",
                        "pcm_s16le",
                        str(target),
                    ]
                    result = subprocess.run(
                        concat_command, capture_output=True, text=True, timeout=120
                    )
                    if result.returncode == 0 and target.is_file():
                        with wave.open(str(target), "rb") as audio:
                            final_duration = audio.getnframes() / float(audio.getframerate())
                        if 5.0 <= final_duration <= 10.0:
                            print(
                                f"Combined {len(voice_clips[voice_id])} clips from one synthetic male voice: "
                                f"{final_duration:.2f}s.",
                                flush=True,
                            )
                            return
                    target.unlink(missing_ok=True)

            print(
                f"Scanned dataset page {offset // 100 + 1}: "
                f"{page_male_rows} male rows; {male_rows} total male rows checked.",
                flush=True,
            )
            if total_rows and offset + 100 >= total_rows:
                break

    raise RuntimeError(
        f"No 5–10 second male synthetic Armenian reference found: "
        f"{male_rows} male rows and {audio_candidates} audio candidates checked."
    )


def prepare_armenian(root: Path, ffmpeg: Path) -> None:
    target = root / "armenian"
    revision = HfApi().model_info(ARMENIAN_MODEL).sha
    print(
        f"Downloading pinned Armenian/Russian/English Pocket TTS fine-tune {revision}…",
        flush=True,
    )
    snapshot_download(
        repo_id=ARMENIAN_MODEL,
        repo_type="model",
        revision=revision,
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
        "The packaged voice is conditioned on a short synthetic Armenian male audio sample.\n",
        encoding="utf-8",
    )
    (target / "REFERENCE_NOTICE.txt").write_text(
        "Reference audio source: ErikMkrtchyan/Hy-Generated-audio-data-2, generated split.\n"
        "Dataset card declares CC0 1.0. The selected voice is a synthetic Armenian male sample, not a real speaker recording.\n"
        "VoiceReader Pro retains only the short audio crop; speaker IDs and other metadata are not packaged.\n"
        "Dataset: https://huggingface.co/datasets/ErikMkrtchyan/Hy-Generated-audio-data-2\n",
        encoding="utf-8",
    )
    (target / "POCKET_TTS_LICENSE.txt").write_text(
        "Pocket TTS upstream software is licensed under the MIT License.\n"
        "Copyright (c) Kyutai.\n"
        "https://github.com/kyutai-labs/pocket-tts\n",
        encoding="utf-8",
    )
    print("Armenian Pocket TTS model, Russian normalizer and synthetic reference clip verified.", flush=True)


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
