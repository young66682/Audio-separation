#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心分离引擎 —— 封装 Demucs CLI，将音频分离为独立音轨。
"""

import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from .config import HAS_DEMUCS, SUPPORTED_STEMS
from .exporter import MP3Exporter


class StemSeparator:
    """基于 Demucs 的音频音轨分离器。"""

    def __init__(self, model_name: str = "htdemucs", device: Optional[str] = None):
        if not HAS_DEMUCS:
            raise RuntimeError("demucs 未安装，请执行: pip install demucs")

        self.model_name = model_name
        self.device = device or self._detect_device()
        self.separator = None
        self._init_separator()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_device() -> str:
        """自动检测可用的计算设备（CUDA > MPS > CPU）。"""
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _init_separator(self) -> None:
        """初始化分离器（当前仅使用 CLI 模式）。"""
        try:
            self.separator = "cli"
            print(f"✅ 分离器已初始化 —— 模型: {self.model_name}, 设备: {self.device}")
        except Exception as exc:
            print(f"警告: 初始化失败: {exc}")
            self.separator = None

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def separate(
        self,
        input_file: Path,
        selected_stems: List[str],
        output_dir: Path,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Path]:
        """
        对单个音频文件执行音轨分离。

        Args:
            input_file:   输入音频文件路径。
            selected_stems: 需要导出的音轨列表（如 ["vocals", "drums"]）。
            output_dir:   最终输出目录（存放 MP3）。
            progress_callback: 进度回调 (msg: str, pct: int) -> None。

        Returns:
            {stem_name: mp3_path} 字典。
        """
        if not input_file.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_file}")

        results: Dict[str, Path] = {}
        temp_dir = Path(tempfile.mkdtemp(prefix="demucs_temp_"))

        try:
            if progress_callback:
                progress_callback("加载音频文件...", 0)

            stems = self._separate_cli(input_file, temp_dir, progress_callback)

            if progress_callback:
                progress_callback("导出 MP3 文件...", 80)

            exporter = MP3Exporter(str(output_dir), bitrate=192)

            for stem in selected_stems:
                if stem not in stems:
                    continue
                wav_path = stems[stem]
                mp3_path = exporter.convert_to_mp3(wav_path, stem)
                results[stem] = mp3_path
                print(f"✅ {stem} -> {mp3_path}")

            if progress_callback:
                progress_callback("分离完成!", 100)

            return results

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _separate_cli(
        self,
        input_file: Path,
        output_dir: Path,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Path]:
        """通过 demucs CLI 执行分离，返回 {stem_name: wav_path}。"""
        demucs_output = output_dir / self.model_name

        cmd = [
            "python",
            "-m",
            "demucs",
            "--out",
            str(output_dir),
            "--name",
            self.model_name,
            "--device",
            self.device,
            str(input_file),
        ]

        if progress_callback:
            progress_callback("运行 demucs 分离...", 20)

        print(f"\n🎵 开始分离: {input_file.name}")
        print(f"📋 命令: {' '.join(cmd)}\n")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )

        full_output: List[str] = []
        for line in process.stdout:
            line = line.strip()
            full_output.append(line)
            print(f"  {line}")

        process.wait()

        if process.returncode != 0:
            error_msg = "\n".join(full_output[-10:])
            raise RuntimeError(f"demucs 分离过程失败\n错误详情:\n{error_msg}")

        # 收集生成的 WAV 文件
        stems_result: Dict[str, Path] = {}
        input_basename = input_file.stem

        for stem_name in SUPPORTED_STEMS:
            stem_path = demucs_output / input_basename / f"{stem_name}.wav"
            if stem_path.exists():
                stems_result[stem_name] = stem_path

        return stems_result
