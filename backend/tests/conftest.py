from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def bypass_upload_audio_probe(monkeypatch):
    """API 测试使用轻量假音频，不启动 ffprobe。"""
    from app import main

    monkeypatch.setattr(main, "validate_audio_file", lambda _: 1.0)
