#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audio Separator —— 基于 Demucs 的 AI 器乐分离工具。

将音频文件分离为人声、鼓、贝斯、吉他、钢琴等独立音轨。
"""

__version__ = "2.4.0"
__author__ = "young66682"

from .config import (
    SUPPORTED_STEMS,
    DEMUCS_4STEMS,
    DEMUCS_6STEMS,
    MODEL_CONFIGS,
    HAS_DEMUCS,
    HAS_PYDUB,
    HAS_STREAMLIT,
)
from .engine import StemSeparator
from .exporter import MP3Exporter

__all__ = [
    "StemSeparator",
    "MP3Exporter",
    "SUPPORTED_STEMS",
    "DEMUCS_4STEMS",
    "DEMUCS_6STEMS",
    "MODEL_CONFIGS",
    "HAS_DEMUCS",
    "HAS_PYDUB",
    "HAS_STREAMLIT",
]
