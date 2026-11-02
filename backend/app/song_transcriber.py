"""Full-song dual-guitar separation and transcription pipeline."""

from __future__ import annotations

import os
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .mvsep import MvsepProvider, SeparationResult
from .schemas import TranscriptionOptions
from .transcriber import GuitarTranscriber, detect_bpm
from .guitar import combine_musicxml


@dataclass(frozen=True)
class SongPipelineOutcome:
    status: Literal["succeeded", "partial"]
    result: dict


class SongTranscriber:
    """Separate lead/rhythm guitars and transcribe both independently."""

    guitar_definitions = (
        ("lead", "主音吉他"),
        ("rhythm", "节奏吉他"),
    )

    def __init__(
        self,
        transcriber: GuitarTranscriber | None = None,
        separator: MvsepProvider | None = None,
    ) -> None:
        self.transcriber = transcriber or GuitarTranscriber()
        self._provided_separator = separator

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        original_filename: str,
        options: TranscriptionOptions,
        progress_callback=None,
    ) -> SongPipelineOutcome:
        output_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []

        if options.bpm > 0:
            bpm = float(options.bpm)
        else:
            progress_callback and progress_callback(
                1, "analyzing_tempo", "正在分析整曲速度"
            )
            bpm, tempo_warnings = detect_bpm(audio_path)
            warnings.extend(tempo_warnings)

        separator = self._provided_separator or MvsepProvider()
        try:
            stems = separator.separate(
                audio_path,
                output_dir / "stems",
                lambda value, message: progress_callback
                and progress_callback(value, "separating", message),
            )
        finally:
            if self._provided_separator is None:
                separator.close()

        progress_callback and progress_callback(
            56,
            "normalizing",
            "正在统一两个吉他音轨的响度",
        )
        stems, normalization_warnings = self._normalize_stems(stems)
        warnings.extend(normalization_warnings)

        guitar_results = []
        successful = 0
        for index, (key, label) in enumerate(self.guitar_definitions):
            start_progress = 58 + index * 21
            stem_path = getattr(stems, key)
            progress_callback and progress_callback(
                start_progress,
                f"transcribing_{key}",
                f"正在为{label}生成六线谱",
            )
            try:
                transcription = self.transcriber.transcribe(
                    stem_path,
                    output_dir / "guitars" / key,
                    f"{Path(original_filename).stem}-{key}{stem_path.suffix}",
                    TranscriptionOptions(
                        bpm=bpm,
                        tuning=options.tuning,
                        capo=options.capo,
                        max_fret=options.max_fret,
                        max_fret_span=options.max_fret_span,
                        min_duration_seconds=options.min_duration_seconds,
                        min_velocity=options.min_velocity,
                    ),
                    lambda value, stage, message, base=start_progress: (
                        progress_callback
                        and progress_callback(
                            base + int(value * 0.21),
                            stage,
                            message,
                        )
                    ),
                )
                successful += 1
                warnings.extend(
                    warning for warning in transcription["warnings"]
                    if warning not in warnings
                )
                guitar_results.append(
                    {
                        "key": key,
                        "label": label,
                        "audio_format": stem_path.suffix.lstrip("."),
                        "transcription": transcription,
                        "error": None,
                    }
                )
            except Exception as exc:
                guitar_results.append(
                    {
                        "key": key,
                        "label": label,
                        "audio_format": stem_path.suffix.lstrip("."),
                        "transcription": None,
                        "error": str(exc),
                    }
                )

        if successful == 0:
            errors = "；".join(
                f"{item['label']}: {item['error']}" for item in guitar_results
            )
            raise RuntimeError(f"两把吉他都未能生成六线谱：{errors}")

        score_parts = []
        for item in guitar_results:
            musicxml_path = (
                output_dir
                / "guitars"
                / item["key"]
                / GuitarTranscriber.artifacts["musicxml"]
            )
            if item["transcription"] is not None and musicxml_path.exists():
                score_parts.append(
                    (item["key"], item["label"], musicxml_path)
                )
        score_artifact = None
        if score_parts:
            combined_path = output_dir / "guitar-score.musicxml"
            combine_musicxml(
                score_parts,
                combined_path,
                Path(original_filename).stem,
                capo=options.capo,
            )
            score_artifact = combined_path.name

        result = {
            "title": Path(original_filename).stem,
            "bpm": bpm,
            "source": "mvsep-lead-rhythm",
            "guitars": guitar_results,
            "backing_available": stems.backing is not None,
            "warnings": warnings,
            "score_artifact": score_artifact,
        }
        self._write_archive(output_dir, result["title"])
        progress_callback and progress_callback(
            100,
            "completed",
            "双吉他分离与扒谱完成",
        )
        return SongPipelineOutcome(
            status="partial" if successful < 2 else "succeeded",
            result=result,
        )

    @staticmethod
    def _normalize_stems(
        stems: SeparationResult,
    ) -> tuple[SeparationResult, list[str]]:
        warnings: list[str] = []
        normalized: dict[str, Path | None] = {}
        for key, source in (
            ("lead", stems.lead),
            ("rhythm", stems.rhythm),
            ("backing", stems.backing),
        ):
            if source is None:
                normalized[key] = None
                continue
            raw = source.with_name(f"{key}-raw{source.suffix}")
            temporary = source.with_name(f"{key}-normalized.flac")
            try:
                if not raw.exists():
                    source.replace(raw)
                completed = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(raw),
                        "-af",
                        "loudnorm=I=-18:TP=-1.5:LRA=11",
                        "-ar",
                        "44100",
                        "-c:a",
                        "flac",
                        str(temporary),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                if completed.returncode != 0 or not temporary.exists():
                    raise RuntimeError(completed.stderr.strip() or "ffmpeg 失败")
                os.replace(temporary, source)
                normalized[key] = source
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                if raw.exists() and not source.exists():
                    raw.replace(source)
                normalized[key] = source if source.exists() else raw
                warnings.append(f"{key} 音轨响度标准化失败：{exc}")

        return (
            SeparationResult(
                lead=normalized["lead"] or stems.lead,
                rhythm=normalized["rhythm"] or stems.rhythm,
                backing=normalized["backing"] or stems.backing,
            ),
            warnings,
        )

    @staticmethod
    def _write_archive(output_dir: Path, title: str) -> Path:
        safe_title = "".join(
            character if character not in '\\/:*?"<>|' else "_"
            for character in title
        ).strip() or "guitar-transcription"
        archive_path = output_dir / f"{safe_title}-guitar-tabs.zip"
        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in output_dir.rglob("*"):
                if not path.is_file() or path == archive_path:
                    continue
                archive.write(path, path.relative_to(output_dir))
        return archive_path
