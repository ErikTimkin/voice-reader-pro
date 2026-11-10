from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

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


def _is_male(value: object) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"female", "female_feminine", "f", "woman"}:
        return False
    return normalized in {"male", "male_masculine", "m", "man"} or normalized.startswith(
        "male_"
    )


def _audio_parts(audio: object) -> tuple[bytes | None, str | None]:
    """Return embedded audio bytes and an optional repository-relative path."""
    if not isinstance(audio, dict):
        return None, None
    raw = audio.get("bytes")
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    if not isinstance(raw, bytes) or not raw:
        raw = None
    path = audio.get("path")
    return raw, str(path) if path else None


def _convert_audio_file(
    source: Path,
    ffmpeg: Path,
    temporary_dir: Path,
    index: int,
) -> tuple[Path, float]:
    output_path = temporary_dir / f"clip-{index}.wav"
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
            "FFmpeg could not convert the Armenian reference clip: "
            + result.stderr[-800:]
        )
    with wave.open(str(output_path), "rb") as audio:
        duration = audio.getnframes() / float(audio.getframerate())
    return output_path, duration


def download_armenian_reference(root: Path, ffmpeg: Path) -> None:
    """Read a short male reference directly from a pinned Hub Parquet shard.

    This deliberately avoids datasets-server's rows endpoint: its rate limits
    and audio URL representation are not reliable for large audio datasets.
    The dataset is CC0-1.0. Only a short audio crop is copied into the app.
    """
    from huggingface_hub import HfApi, hf_hub_download
    import pyarrow.parquet as pq

    target_dir = root / "armenian"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "armenian_reference.wav"
    if target.is_file() and target.stat().st_size > 10_000:
        with wave.open(str(target), "rb") as existing:
            duration = existing.getnframes() / float(existing.getframerate())
        if 5.0 <= duration <= 10.0:
            print(f"Using existing Armenian reference clip: {duration:.2f}s.", flush=True)
            return
        target.unlink(missing_ok=True)

    api = HfApi()
    info = api.dataset_info(ARMENIAN_DATASET)
    revision = info.sha
    repo_files = api.list_repo_files(
        repo_id=ARMENIAN_DATASET,
        repo_type="dataset",
        revision=revision,
    )
    shards = sorted(
        name
        for name in repo_files
        if name.startswith("data/")
        and name.endswith(".parquet")
        and "generated-" in Path(name).name
    )
    if not shards:
        raise RuntimeError(
            f"No generated Parquet shards were found in {ARMENIAN_DATASET}."
        )

    print(
        f"Downloading a pinned Armenian dataset shard at revision {revision[:12]} "
        "to extract a CC0 synthetic male reference…",
        flush=True,
    )

    total_male_rows = 0
    total_audio_rows = 0
    converted_rows = 0
    clip_index = 0

    with tempfile.TemporaryDirectory(prefix="armenian-reference-") as temp_name:
        temporary_dir = Path(temp_name)
        voice_clips: dict[str, list[tuple[Path, float]]] = {}

        # One shard is about 450 MB and contains thousands of examples. A
        # second shard is attempted only if the first one has no usable sample.
        for shard_name in shards[:2]:
            shard_path = Path(
                hf_hub_download(
                    repo_id=ARMENIAN_DATASET,
                    repo_type="dataset",
                    filename=shard_name,
                    revision=revision,
                )
            )
            print(
                f"Downloaded {Path(shard_name).name} "
                f"({shard_path.stat().st_size / (1024 * 1024):.0f} MB).",
                flush=True,
            )
            parquet_file = pq.ParquetFile(str(shard_path))
            available = set(parquet_file.schema_arrow.names)
            if not {"audio", "gender"}.issubset(available):
                raise RuntimeError(
                    f"Unexpected Armenian dataset columns in {shard_name}: "
                    f"{sorted(available)}"
                )
            columns = ["audio", "gender"]
            if "client_id" in available:
                columns.append("client_id")

            for batch in parquet_file.iter_batches(batch_size=64, columns=columns):
                audio_values = batch.column(batch.schema.get_field_index("audio"))
                gender_values = batch.column(batch.schema.get_field_index("gender"))
                client_values = (
                    batch.column(batch.schema.get_field_index("client_id"))
                    if "client_id" in columns
                    else None
                )

                for row_index in range(batch.num_rows):
                    if not _is_male(gender_values[row_index].as_py()):
                        continue
                    total_male_rows += 1

                    audio_bytes, audio_path = _audio_parts(
                        audio_values[row_index].as_py()
                    )
                    source_path: Path | None = None
                    if audio_bytes:
                        clip_index += 1
                        source_path = temporary_dir / f"source-{clip_index}.audio"
                        source_path.write_bytes(audio_bytes)
                    elif audio_path:
                        # Some Parquet variants store a repository path instead
                        # of embedding audio bytes. Resolve it at the same pin.
                        try:
                            source_path = Path(
                                hf_hub_download(
                                    repo_id=ARMENIAN_DATASET,
                                    repo_type="dataset",
                                    filename=audio_path,
                                    revision=revision,
                                )
                            )
                        except Exception as exc:
                            print(
                                f"Skipping a missing audio asset in {shard_name}: {exc}",
                                flush=True,
                            )
                            continue
                    else:
                        continue

                    total_audio_rows += 1
                    clip_index += 1
                    try:
                        converted, duration = _convert_audio_file(
                            source_path,
                            ffmpeg,
                            temporary_dir,
                            clip_index,
                        )
                    except Exception as exc:
                        print(
                            f"Skipping an unreadable Armenian audio sample: {exc}",
                            flush=True,
                        )
                        continue
                    converted_rows += 1

                    if 5.0 <= duration <= 10.0:
                        shutil.copy2(converted, target)
                        print(
                            f"Selected a synthetic male Armenian reference: {duration:.2f}s.",
                            flush=True,
                        )
                        return

                    speaker_id = (
                        str(client_values[row_index].as_py())
                        if client_values is not None
                        and client_values[row_index].as_py()
                        else f"single-{clip_index}"
                    )
                    speaker_samples = voice_clips.setdefault(speaker_id, [])
                    if len(speaker_samples) < 4:
                        speaker_samples.append((converted, duration))
                    if sum(item[1] for item in speaker_samples) < 5.0:
                        continue

                    list_file = temporary_dir / f"concat-{clip_index}.txt"
                    entries = [
                        "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'"
                        for path, _ in speaker_samples
                    ]
                    list_file.write_text(
                        "\n".join(entries) + "\n",
                        encoding="utf-8",
                    )
                    combined_path = temporary_dir / f"combined-{clip_index}.wav"
                    command = [
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
                        str(combined_path),
                    ]
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode == 0 and combined_path.is_file():
                        with wave.open(str(combined_path), "rb") as audio:
                            final_duration = (
                                audio.getnframes() / float(audio.getframerate())
                            )
                        if 5.0 <= final_duration <= 10.0:
                            shutil.copy2(combined_path, target)
                            print(
                                f"Combined {len(speaker_samples)} clips from one "
                                f"synthetic male Armenian voice: {final_duration:.2f}s.",
                                flush=True,
                            )
                            return

            print(
                f"Scanned {Path(shard_name).name}: {total_male_rows} male rows, "
                f"{total_audio_rows} audio records, {converted_rows} converted.",
                flush=True,
            )

    raise RuntimeError(
        "Could not extract a 5–10 second synthetic male Armenian reference "
        f"from the first {min(2, len(shards))} pinned Parquet shard(s): "
        f"{total_male_rows} male rows, {total_audio_rows} audio records, "
        f"{converted_rows} converted. No fallback voice was substituted."
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
        ],
    )

    weights = target / "tri_v1" / "model.safetensors"
    tokenizer = target / "tri_v1" / "tokenizer_tri.model"
    for path in (weights, tokenizer):
        if not path.is_file() or path.stat().st_size < 100:
            raise RuntimeError(f"Armenian model file is missing or incomplete: {path}")

    import yaml
    import pocket_tts

    base_config = Path(pocket_tts.__file__).parent / "config" / "english_2026-09_24l.yaml"
    if not base_config.is_file():
        raise FileNotFoundError(f"Pocket TTS base config not found: {base_config}")
    config = yaml.safe_load(base_config.read_text(encoding="utf-8"))
    # Runtime replaces these portable markers with paths relative to the
    # installed voices/armenian folder. Never embed a CI runner's absolute path.
    config["weights_path"] = "__VOICE_ASSET_ROOT__/tri_v1/model.safetensors"
    config.pop("weights_path_without_voice_cloning", None)
    lookup = config["flow_lm"]["lookup_table"]
    lookup["n_bins"] = 12000
    lookup["tokenizer"] = "sentencepiece"
    lookup["tokenizer_path"] = "__VOICE_ASSET_ROOT__/tri_v1/tokenizer_tri.model"

    config_path = target / "armenian_tri.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    download_armenian_reference(root, ffmpeg)

    # Precompute the speaker conditioning state during the Windows build.
    # This removes the expensive audio-reference encoding from the user's first
    # Armenian message; the packaged .safetensors state is portable.
    from pocket_tts import TTSModel, export_model_state
    import torch
    torch.set_num_threads(max(1, min(6, __import__("os").cpu_count() or 2)))
    runtime_config = dict(config)
    runtime_config["weights_path"] = str(weights.resolve())
    runtime_config["flow_lm"]["lookup_table"]["tokenizer_path"] = str(tokenizer.resolve())
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".yaml",
        prefix="voice-reader-armenian-build-", delete=False,
    ) as temp_config:
        yaml.safe_dump(runtime_config, temp_config, allow_unicode=True, sort_keys=False)
        runtime_config_path = Path(temp_config.name)
    try:
        print("Precomputing Armenian speaker state for faster first use…", flush=True)
        tts_model = TTSModel.load_model(config=str(runtime_config_path))
        voice_state = tts_model.get_state_for_audio_prompt(str(target / "armenian_reference.wav"))
        export_model_state(voice_state, target / "armenian_voice_state.safetensors")
        del voice_state, tts_model
    finally:
        runtime_config_path.unlink(missing_ok=True)
    state_file = target / "armenian_voice_state.safetensors"
    if not state_file.is_file() or state_file.stat().st_size < 100:
        raise RuntimeError("Failed to precompute portable Armenian speaker state.")

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
    print("Armenian/Russian/English Pocket TTS model and synthetic male reference clip verified.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    args = parser.parse_args()
    args.voices_dir.mkdir(parents=True, exist_ok=True)
    if not args.ffmpeg.is_file():
        raise FileNotFoundError(args.ffmpeg)

    prepare_armenian(args.voices_dir, args.ffmpeg)


if __name__ == "__main__":
    main()
