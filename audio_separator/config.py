#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局配置 —— 模型定义、音轨映射、依赖可用性检测。
"""

# ---------------------------------------------------------------------------
# 依赖可用性检测
# ---------------------------------------------------------------------------

try:
    import streamlit as st  # noqa: F401

    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

try:
    from demucs.separate import main as demucs_separate  # noqa: F401

    HAS_DEMUCS = True
except ImportError:
    HAS_DEMUCS = False

try:
    from pydub import AudioSegment  # noqa: F401

    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    from tqdm import tqdm  # noqa: F401

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

try:
    import pyperclip  # noqa: F401

    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

# ---------------------------------------------------------------------------
# 支持分离的音轨
# ---------------------------------------------------------------------------

SUPPORTED_STEMS = {
    "vocals": "🎤 人声 (Vocals)",
    "drums": "🥁 鼓 (Drums)",
    "bass": "🎸 贝斯 (Bass)",
    "guitar": "🎸 吉他 (Guitar)",
    "piano": "🎹 钢琴 (Piano)",
    "other": "🎵 其他乐器 (Other)",
}

DEMUCS_4STEMS = ["vocals", "drums", "bass", "other"]
DEMUCS_6STEMS = ["vocals", "drums", "bass", "guitar", "piano", "other"]

# ---------------------------------------------------------------------------
# 预置模型配置
# ---------------------------------------------------------------------------

MODEL_CONFIGS = {
    "htdemucs": {
        "name": "HTDemucs (默认, 高质量)",
        "stems": DEMUCS_4STEMS,
        "description": "Hybrid Transformer Demucs v4 —— 最新架构，仅支持 4 轨：人声/鼓/贝斯/其他",
        "icon": "⚡",
        "supports_guitar": False,
    },
    "htdemucs_6s": {
        "name": "HTDemucs 6-Stem (实验性)",
        "stems": DEMUCS_6STEMS,
        "description": "六轨分离模型，支持吉他和钢琴（实验性）",
        "icon": "🔬",
        "supports_guitar": True,
    },
    "mdx_q": {
        "name": "MDX (快速模式)",
        "stems": DEMUCS_4STEMS,
        "description": "MDX 量化模型，速度较快但质量稍低，仅支持 4 轨",
        "icon": "🚀",
        "supports_guitar": False,
    },
}
