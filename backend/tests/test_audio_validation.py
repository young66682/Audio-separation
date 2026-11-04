from __future__ import annotations

import wave
from pathlib import Path

import pytest

from app.audio_validation import AudioValidationError, validate_audio_file


def test_audio_validation_reads_wav_duration(tmp_path: Path) -> None:
    path = tmp_path / "valid.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 800)

    assert validate_audio_file(path) == pytest.approx(0.1, abs=0.02)


def test_audio_validation_rejects_non_audio(tmp_path: Path) -> None:
    path = tmp_path / "broken.wav"
    path.write_bytes(b"not an audio file")

    with pytest.raises(AudioValidationError):
        validate_audio_file(path)
