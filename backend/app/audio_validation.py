"""上传音频的基础有效性校验。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class AudioValidationError(ValueError):
    """上传内容不是可读取音频时抛出。"""


def validate_audio_file(path: Path) -> float:
    """使用 ffprobe 确认文件包含可解码音轨并返回时长。"""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise AudioValidationError("服务器缺少 ffprobe，无法校验上传音频")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise AudioValidationError("无法读取该音频文件，请确认文件没有损坏")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AudioValidationError("ffprobe 返回了无效结果") from exc
    audio_streams = [
        stream
        for stream in payload.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    if not audio_streams:
        raise AudioValidationError("文件中没有可读取的音频流")
    duration = payload.get("format", {}).get("duration")
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        duration_value = max(
            (
                float(stream.get("duration") or 0)
                for stream in audio_streams
            ),
            default=0.0,
        )
    if duration_value <= 0:
        raise AudioValidationError("音频时长无效")
    return duration_value
