"""本地 Demucs 音轨分离与指定乐器伴奏生成。"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import (
    DEMUCS_DEVICE,
    DEMUCS_JOB_TIMEOUT_SECONDS,
)


ProgressCallback = Callable[[int, str, str], None]
DEMUCS_PROGRESS_RE = re.compile(r"(\d{1,3})%")


@dataclass(frozen=True)
class SeparationModel:
    key: str
    label: str
    description: str
    stems: tuple[str, ...]
    memory_hint: str


STEM_LABELS = {
    "vocals": "人声",
    "drums": "鼓组",
    "bass": "贝斯",
    "guitar": "吉他",
    "piano": "钢琴",
    "other": "其他乐器",
}

SEPARATION_MODELS = {
    "htdemucs": SeparationModel(
        key="htdemucs",
        label="HTDemucs 4 轨",
        description="默认模型，分离人声、鼓、贝斯和其他乐器，速度与质量均衡。",
        stems=("vocals", "drums", "bass", "other"),
        memory_hint="推荐",
    ),
    "htdemucs_6s": SeparationModel(
        key="htdemucs_6s",
        label="HTDemucs 6 轨",
        description="额外拆分吉他和钢琴，适合制作指定乐器伴奏；速度较慢。",
        stems=("vocals", "drums", "bass", "guitar", "piano", "other"),
        memory_hint="精细",
    ),
    "mdx_extra_q": SeparationModel(
        key="mdx_extra_q",
        label="MDX Extra Q 4 轨",
        description="高质量 MDX 模型，适合质量优先的 4 轨分离，CPU 上较慢。",
        stems=("vocals", "drums", "bass", "other"),
        memory_hint="高质量",
    ),
}

QUALITY_SETTINGS = {
    "fast": {"shifts": 0, "overlap": 0.1, "label": "快速"},
    "balanced": {"shifts": 1, "overlap": 0.25, "label": "均衡"},
    "best": {"shifts": 2, "overlap": 0.5, "label": "高质量"},
}


class LocalSeparationError(RuntimeError):
    """本地 Demucs 分离或伴奏混音失败时抛出。"""


def separation_ready() -> bool:
    return (
        importlib.util.find_spec("demucs") is not None
        and importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("soundfile") is not None
        and shutil.which("ffmpeg") is not None
    )


def detect_device() -> str:
    if DEMUCS_DEVICE in {"cpu", "cuda", "mps"}:
        return DEMUCS_DEVICE
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if (
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            return "mps"
    except Exception:
        pass
    return "cpu"


def model_catalog() -> list[dict[str, object]]:
    return [
        {
            "key": model.key,
            "label": model.label,
            "description": model.description,
            "stems": [
                {"key": stem, "label": STEM_LABELS[stem]}
                for stem in model.stems
            ],
            "memory_hint": model.memory_hint,
        }
        for model in SEPARATION_MODELS.values()
    ]


def _report(
    callback: ProgressCallback | None,
    progress: int,
    stage: str,
    message: str,
) -> None:
    if callback:
        callback(progress, stage, message)


def _probe_duration(audio_path: Path) -> float | None:
    executable = shutil.which("ffprobe")
    if executable is None:
        return None
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return round(float(completed.stdout.strip()), 3)
    except ValueError:
        return None


class LocalSeparator:
    """在当前 Python 环境中运行 Demucs，并混合生成伴奏文件。"""

    def separate(
        self,
        audio_path: Path,
        output_dir: Path,
        model_name: str,
        remove_stems: list[str],
        quality: str = "balanced",
        progress_callback: ProgressCallback | None = None,
        title: str | None = None,
    ) -> dict[str, object]:
        if not separation_ready():
            raise LocalSeparationError(
                "本地分离引擎未就绪。请安装后端 Demucs 依赖并确保 ffmpeg 可用。"
            )
        model = SEPARATION_MODELS.get(model_name)
        if model is None:
            raise ValueError(f"未知分离模型: {model_name}")
        if quality not in QUALITY_SETTINGS:
            raise ValueError(f"未知分离质量: {quality}")

        remove_stems = list(dict.fromkeys(remove_stems))
        invalid = [stem for stem in remove_stems if stem not in model.stems]
        if invalid:
            raise ValueError(
                f"模型 {model.label} 不支持这些音轨: {', '.join(invalid)}"
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        stems_dir = output_dir / "stems"
        accompaniment_dir = output_dir / "accompaniments"
        raw_dir = output_dir / ".demucs"
        stems_dir.mkdir(parents=True, exist_ok=True)
        accompaniment_dir.mkdir(parents=True, exist_ok=True)

        device = detect_device()
        duration = _probe_duration(audio_path)
        _report(
            progress_callback,
            2,
            "loading_model",
            f"正在加载 {model.label}（{device.upper()}）",
        )

        raw_stems = self._run_demucs(
            audio_path,
            raw_dir,
            model,
            quality,
            device,
            progress_callback,
        )
        _report(
            progress_callback,
            80,
            "collecting",
            "正在整理分离音轨",
        )

        stems: dict[str, Path] = {}
        for stem in model.stems:
            source = raw_stems.get(stem)
            if source is None:
                raise LocalSeparationError(
                    f"Demucs 未生成 {STEM_LABELS[stem]} 音轨"
                )
            destination = stems_dir / f"{stem}{source.suffix.lower()}"
            shutil.move(str(source), destination)
            stems[stem] = destination

        accompaniment_files: dict[str, Path] = {}
        for index, removed_stem in enumerate(remove_stems):
            remaining = [
                stems[stem]
                for stem in model.stems
                if stem != removed_stem
            ]
            if not remaining:
                raise ValueError("不能移除全部音轨后再生成伴奏")
            progress = 82 + int(
                (index / max(1, len(remove_stems))) * 13
            )
            _report(
                progress_callback,
                progress,
                "mixing_accompaniment",
                f"正在生成去掉{STEM_LABELS[removed_stem]}的伴奏",
            )
            destination = accompaniment_dir / f"without-{removed_stem}.flac"
            self._mix_accompaniment(remaining, destination)
            accompaniment_files[removed_stem] = destination

        _report(
            progress_callback,
            96,
            "archiving",
            "正在生成清单与项目压缩包",
        )
        shutil.rmtree(raw_dir, ignore_errors=True)

        output_title = Path(title).stem if title else audio_path.stem
        output_title = output_title or "audio-separation"
        result: dict[str, object] = {
            "title": output_title,
            "model": {
                "key": model.key,
                "label": model.label,
            },
            "device": device,
            "quality": quality,
            "duration_seconds": duration,
            "stems": [
                {
                    "key": stem,
                    "label": STEM_LABELS[stem],
                    "filename": stems[stem].name,
                    "audio_format": stems[stem].suffix.lstrip("."),
                }
                for stem in model.stems
            ],
            "accompaniments": [
                {
                    "key": stem,
                    "label": f"去掉{STEM_LABELS[stem]}的伴奏",
                    "removed_stem": stem,
                    "removed_label": STEM_LABELS[stem],
                    "filename": accompaniment_files[stem].name,
                    "audio_format": accompaniment_files[stem].suffix.lstrip("."),
                }
                for stem in remove_stems
            ],
            "warnings": [],
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        archive_path = output_dir / f"{self._safe_stem(output_title)}-stems.zip"
        self._write_archive(output_dir, archive_path)
        result["archive_filename"] = archive_path.name
        manifest_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    def _run_demucs(
        self,
        audio_path: Path,
        raw_dir: Path,
        model: SeparationModel,
        quality: str,
        device: str,
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Path]:
        raw_dir.mkdir(parents=True, exist_ok=True)
        settings = QUALITY_SETTINGS[quality]
        command = [
            sys.executable,
            str(Path(__file__).with_name("demucs_runner.py")),
            "--out",
            str(raw_dir),
            "--name",
            model.key,
            "--device",
            device,
            "--flac",
            "--shifts",
            str(settings["shifts"]),
            "--overlap",
            str(settings["overlap"]),
            str(audio_path),
        ]
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
        tail: deque[str] = deque(maxlen=80)
        reader_errors: list[Exception] = []

        def read_output() -> None:
            line_buffer = ""
            last_reported = -1
            assert process.stdout is not None
            try:
                while character := process.stdout.read(1):
                    if character not in {"\r", "\n"}:
                        line_buffer += character
                        continue
                    line = line_buffer.strip()
                    line_buffer = ""
                    if not line:
                        continue
                    tail.append(line)
                    print(f"[demucs] {line}", flush=True)
                    match = DEMUCS_PROGRESS_RE.search(line)
                    if not match:
                        continue
                    remote_progress = min(100, int(match.group(1)))
                    mapped_progress = 5 + int(remote_progress * 0.73)
                    if mapped_progress <= last_reported:
                        continue
                    last_reported = mapped_progress
                    _report(
                        progress_callback,
                        mapped_progress,
                        "separating",
                        f"Demucs 正在分离（{remote_progress}%）",
                    )
            except Exception as exc:
                reader_errors.append(exc)

        reader = threading.Thread(
            target=read_output,
            name="demucs-output-reader",
            daemon=True,
        )
        reader.start()
        try:
            process.wait(timeout=DEMUCS_JOB_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            reader.join(timeout=5)
            raise LocalSeparationError(
                f"Demucs 处理超时（{DEMUCS_JOB_TIMEOUT_SECONDS // 60} 分钟）"
            ) from exc
        reader.join(timeout=5)
        if reader_errors:
            raise LocalSeparationError(
                f"读取 Demucs 日志失败：{reader_errors[0]}"
            ) from reader_errors[0]
        if process.returncode != 0:
            details = "\n".join(tail)
            raise LocalSeparationError(
                "Demucs 分离失败"
                + (f"：{details}" if details else f"（退出码 {process.returncode}）")
            )

        found: dict[str, Path] = {}
        for path in raw_dir.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in {".flac", ".wav", ".mp3", ".ogg"}
                and path.stem in model.stems
                and path.stem not in found
            ):
                found[path.stem] = path

        missing = [stem for stem in model.stems if stem not in found]
        if missing:
            raise LocalSeparationError(
                "Demucs 输出不完整，缺少音轨: " + ", ".join(missing)
            )
        return found

    @staticmethod
    def _mix_accompaniment(sources: list[Path], destination: Path) -> None:
        if len(sources) == 1:
            shutil.copy2(sources[0], destination)
            return

        command = [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for source in sources:
            command.extend(["-i", str(source)])
        streams = "".join(f"[{index}:a]" for index in range(len(sources)))
        command.extend(
            [
                "-filter_complex",
                (
                    f"{streams}amix=inputs={len(sources)}:duration=longest:"
                    "dropout_transition=0:normalize=0,"
                    "alimiter=limit=0.95:level=false[out]"
                ),
                "-map",
                "[out]",
                "-c:a",
                "flac",
                str(destination),
            ]
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0 or not destination.exists():
            destination.unlink(missing_ok=True)
            detail = completed.stderr.strip()
            raise LocalSeparationError(
                "伴奏混音失败" + (f"：{detail}" if detail else "")
            )

    @staticmethod
    def _safe_stem(value: str) -> str:
        safe = "".join(
            character if character not in '\\/:*?"<>|' else "_"
            for character in value
        ).strip()
        return safe or "audio-separation"

    @classmethod
    def _write_archive(cls, output_dir: Path, archive_path: Path) -> None:
        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in output_dir.rglob("*"):
                if (
                    not path.is_file()
                    or path == archive_path
                    or ".demucs" in path.parts
                ):
                    continue
                archive.write(path, path.relative_to(output_dir))
