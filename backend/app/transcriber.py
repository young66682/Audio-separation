"""Basic Pitch driven guitar transcription service."""

from __future__ import annotations

import json
import os
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .guitar import build_tablature, make_tab_text, write_midi, write_musicxml
from .schemas import TranscriptionOptions


ProgressCallback = Callable[[int, str, str], None]
_TRANSCRIPTION_LOCK = threading.Lock()


def _serialized_transcription(function):
    """Basic Pitch shares one TensorFlow model, so serialize local inference."""

    @wraps(function)
    def wrapper(*args, **kwargs):
        with _TRANSCRIPTION_LOCK:
            return function(*args, **kwargs)

    return wrapper


def _report(
    callback: ProgressCallback | None,
    progress: int,
    stage: str,
    message: str,
) -> None:
    if callback:
        callback(progress, stage, message)


def _detect_bpm(audio_path: Path) -> tuple[float, list[str]]:
    warnings: list[str] = []
    try:
        import librosa
        import numpy as np

        samples, sample_rate = librosa.load(str(audio_path), sr=22050, mono=True)
        tempo_result = librosa.beat.beat_track(y=samples, sr=sample_rate)
        tempo_value = np.ravel(tempo_result[0])[0]
        bpm = float(tempo_value)
        if not 30 <= bpm <= 300:
            raise ValueError(f"检测到的 BPM 超出范围: {bpm}")
        return round(bpm, 2), warnings
    except Exception as exc:
        warnings.append(f"自动测速失败，已回退到 120 BPM：{exc}")
        return 120.0, warnings


def detect_bpm(audio_path: Path) -> tuple[float, list[str]]:
    """Public wrapper used by the full-song pipeline."""
    return _detect_bpm(audio_path)


def _normalize_note_events(note_events: Any) -> list[dict[str, float | int]]:
    notes: list[dict[str, float | int]] = []
    for event in note_events or []:
        if len(event) < 4:
            continue
        start = float(event[0])
        end = float(event[1])
        pitch = int(round(float(event[2])))
        amplitude = min(max(float(event[3]), 0.0), 1.0)
        if end <= start:
            continue
        notes.append(
            {
                "start": round(start, 5),
                "end": round(end, 5),
                "pitch": pitch,
                "velocity": round(amplitude, 5),
            }
        )
    return notes


def _midi_frequency(pitch: int) -> float:
    return 440.0 * (2 ** ((pitch - 69) / 12))


def _suppress_harmonic_ghosts(
    notes: list[dict[str, float | int]],
    onset_tolerance: float = 0.08,
) -> tuple[list[dict[str, float | int]], int]:
    """Remove weak upper harmonics that Basic Pitch often doubles as notes."""
    ordered = sorted(notes, key=lambda note: float(note["start"]))
    groups: list[list[dict[str, float | int]]] = []
    for note in ordered:
        if (
            not groups
            or float(note["start"]) - float(groups[-1][0]["start"])
            > onset_tolerance
        ):
            groups.append([note])
        else:
            groups[-1].append(note)

    harmonic_intervals = {19, 24, 28, 31, 36, 40, 43, 48}
    kept: list[dict[str, float | int]] = []
    removed = 0
    for group in groups:
        for note in group:
            is_ghost = any(
                int(note["pitch"]) - int(lower["pitch"]) in harmonic_intervals
                and float(note["velocity"])
                < float(lower.get("velocity", 0)) * 0.8
                and float(note["start"]) < float(lower["end"])
                for lower in group
                if int(lower["pitch"]) < int(note["pitch"])
            )
            if is_ghost:
                removed += 1
            else:
                kept.append(note)
    return kept, removed


class GuitarTranscriber:
    """Generate tablature and score artifacts from a guitar audio file."""

    artifacts = {
        "midi": "guitar.mid",
        "musicxml": "guitar.musicxml",
        "tab": "guitar-tab.txt",
        "json": "transcription.json",
    }

    @_serialized_transcription
    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        original_filename: str,
        options: TranscriptionOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        from .guitar import parse_tuning

        output_dir.mkdir(parents=True, exist_ok=True)
        tuning = parse_tuning(options.tuning)
        if len(tuning) != 6:
            raise ValueError("必须提供六根弦的调弦")

        _report(progress_callback, 5, "preparing", "检查音频与转录参数")
        all_warnings: list[str] = []

        if options.bpm > 0:
            bpm = float(options.bpm)
        else:
            _report(progress_callback, 12, "tempo", "正在估计歌曲速度")
            bpm, tempo_warnings = _detect_bpm(audio_path)
            all_warnings.extend(tempo_warnings)

        _report(progress_callback, 22, "transcribing", "正在识别吉他音高与起音")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        try:
            from basic_pitch.inference import predict
        except Exception as exc:
            raise RuntimeError(
                "Basic Pitch 加载失败。请确认当前使用 Python 3.11 并已安装后端依赖。"
            ) from exc

        lowest_pitch = min(tuning) + options.capo
        highest_pitch = max(tuning) + options.capo + options.max_fret
        _, _, note_events = predict(
            str(audio_path),
            minimum_frequency=_midi_frequency(lowest_pitch),
            maximum_frequency=_midi_frequency(highest_pitch),
            minimum_note_length=options.min_duration_seconds * 1000,
            midi_tempo=bpm,
        )
        raw_notes = _normalize_note_events(note_events)
        filtered_notes = [
            note
            for note in raw_notes
            if float(note["end"]) - float(note["start"])
            >= options.min_duration_seconds
            and float(note["velocity"]) >= options.min_velocity
        ]
        if raw_notes and not filtered_notes:
            raise ValueError("检测到的音符都短于当前最短音符时长，请调低该参数。")
        if not filtered_notes:
            raise ValueError(
                "没有检测到可转录的吉他音符。请使用吉他较清晰的音轨再试。"
            )

        filtered_notes, harmonic_count = _suppress_harmonic_ghosts(filtered_notes)
        if harmonic_count:
            all_warnings.append(
                f"已过滤 {harmonic_count} 个疑似泛音重复音符。"
            )

        _report(progress_callback, 68, "fretboard", "正在分配琴弦和品丝")
        events, tab_warnings = build_tablature(
            filtered_notes,
            bpm=bpm,
            tuning_text=options.tuning,
            capo=options.capo,
            max_fret=options.max_fret,
            max_fret_span=options.max_fret_span,
        )
        all_warnings.extend(tab_warnings)
        if not events:
            raise ValueError(
                "所有识别音符都超出当前调弦与品数范围，请调整调弦或最大品数。"
            )

        _report(progress_callback, 82, "quantizing", "正在量化节拍并生成六线谱")
        tab_text = make_tab_text(events, bpm, options.tuning, options.capo)
        tab_path = output_dir / self.artifacts["tab"]
        tab_path.write_text(tab_text, encoding="utf-8")

        _report(progress_callback, 90, "exporting", "正在导出 MIDI 与 MusicXML")
        midi_path = output_dir / self.artifacts["midi"]
        write_midi(events, bpm, midi_path)
        title = Path(original_filename).stem or "Guitar transcription"
        musicxml_path = output_dir / self.artifacts["musicxml"]
        try:
            write_musicxml(
                events,
                bpm,
                musicxml_path,
                title,
                options.tuning,
            )
        except Exception as exc:
            all_warnings.append(f"MusicXML 导出失败：{exc}")

        available_artifacts = {
            key: name
            for key, name in self.artifacts.items()
            if (output_dir / name).exists()
        }
        available_artifacts["json"] = self.artifacts["json"]
        result = {
            "title": title,
            "bpm": bpm,
            "tuning": options.tuning,
            "capo": options.capo,
            "max_fret": options.max_fret,
            "note_count": len(events),
            "raw_note_count": len(raw_notes),
            "events": events,
            "warnings": all_warnings,
            "tab_text": tab_text,
            "artifacts": available_artifacts,
        }
        (output_dir / self.artifacts["json"]).write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _report(progress_callback, 100, "completed", f"识别完成，共 {len(events)} 个音符")
        return result

