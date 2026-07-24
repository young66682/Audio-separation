#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MP3 导出器 —— 将 WAV 文件转换为 MP3 格式。
"""

import subprocess
from pathlib import Path

from .config import HAS_PYDUB


class MP3Exporter:
    """将 WAV 音频文件导出为 MP3 格式。"""

    def __init__(self, output_dir: str, bitrate: int = 192):
        self.output_dir = Path(output_dir)
        self.bitrate = bitrate
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def convert_to_mp3(self, wav_path: Path, stem_name: str) -> Path:
        """将单个 WAV 文件转换为 MP3。

        Args:
            wav_path:  源 WAV 文件路径。
            stem_name: 音轨名称（用作输出文件名，不含扩展名）。

        Returns:
            生成的 MP3 文件路径。
        """
        mp3_path = self.output_dir / f"{stem_name}.mp3"

        if HAS_PYDUB:
            self._convert_via_pydub(wav_path, mp3_path)
        else:
            self._convert_via_ffmpeg(wav_path, mp3_path)

        return mp3_path

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _convert_via_pydub(self, wav_path: Path, mp3_path: Path) -> None:
        """使用 pydub 进行转换（依赖 FFmpeg）。"""
        from pydub import AudioSegment

        audio = AudioSegment.from_wav(str(wav_path))
        audio.export(str(mp3_path), format="mp3", bitrate=f"{self.bitrate}k")

    def _convert_via_ffmpeg(self, wav_path: Path, mp3_path: Path) -> None:
        """使用 ffmpeg 命令行直接转换。"""
        cmd = [
            "ffmpeg",
            "-i",
            str(wav_path),
            "-acodec",
            "mp3",
            "-ab",
            f"{self.bitrate}k",
            "-y",
            str(mp3_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
