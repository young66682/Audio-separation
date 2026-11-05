from __future__ import annotations

import math
import shutil
import struct
import wave
import zipfile
from pathlib import Path

import pytest

from app.local_separation import (
    SEPARATION_MODELS,
    LocalSeparator,
    _console_safe_text,
    model_catalog,
)
from app.demucs_runner import _install_soundfile_save


def _write_silence(path: Path, seconds: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes(b"\0\0\0\0" * int(44100 * seconds))


def _write_tone(path: Path, frequency: float, seconds: float = 0.25) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    frames = bytearray()
    for index in range(int(sample_rate * seconds)):
        sample = int(7000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<hh", sample, sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def test_model_catalog_exposes_expected_stems() -> None:
    catalog = {item["key"]: item for item in model_catalog()}

    six_stem_model = SEPARATION_MODELS["htdemucs_6s"]
    assert six_stem_model.stems == (
        "vocals",
        "drums",
        "bass",
        "guitar",
        "piano",
        "other",
    )
    assert [stem["key"] for stem in catalog["htdemucs_6s"]["stems"]] == [
        "vocals",
        "drums",
        "bass",
        "guitar",
        "piano",
        "other",
    ]
    assert [stem["key"] for stem in catalog["htdemucs"]["stems"]] == [
        "vocals",
        "drums",
        "bass",
        "other",
    ]


def test_demucs_progress_log_is_safe_for_gbk_console() -> None:
    line = "  5%|█████     | 0.5/10 [00:01<00:19]"

    converted = _console_safe_text(line, "gbk")

    assert "5%" in converted
    assert "\ufffd" not in converted
    converted.encode("gbk")


def test_separation_builds_stems_manifest_accompaniment_and_zip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "song.wav"
    source.write_bytes(b"source")
    separator = LocalSeparator()

    monkeypatch.setattr(
        "app.local_separation.separation_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.local_separation.detect_device",
        lambda: "cpu",
    )
    monkeypatch.setattr(
        "app.local_separation._probe_duration",
        lambda _: 12.5,
    )

    def fake_demucs(
        _audio_path,
        raw_dir,
        model,
        _quality,
        _device,
        _progress_callback,
    ):
        paths = {}
        for stem in model.stems:
            path = raw_dir / model.key / "input" / f"{stem}.flac"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(stem.encode())
            paths[stem] = path
        return paths

    def fake_mix(sources, destination):
        assert sources
        destination.write_bytes(b"mixed")

    monkeypatch.setattr(separator, "_run_demucs", fake_demucs)
    monkeypatch.setattr(separator, "_mix_accompaniment", fake_mix)
    progress: list[tuple[int, str, str]] = []

    result = separator.separate(
        source,
        tmp_path / "output",
        "htdemucs_6s",
        ["vocals", "guitar"],
        "balanced",
        lambda value, stage, message: progress.append((value, stage, message)),
    )

    output = tmp_path / "output"
    assert len(result["stems"]) == 6
    assert len(result["accompaniments"]) == 2
    assert result["duration_seconds"] == 12.5
    assert (output / "stems" / "guitar.flac").read_bytes() == b"guitar"
    assert (output / "accompaniments" / "without-vocals.flac").exists()
    assert (output / "accompaniments" / "without-guitar.flac").exists()
    assert (output / "manifest.json").exists()
    with zipfile.ZipFile(output / str(result["archive_filename"])) as archive:
        names = set(archive.namelist())
    assert "manifest.json" in names
    assert "stems/vocals.flac" in names
    assert "accompaniments/without-vocals.flac" in names
    assert progress[-1][1] == "archiving"


def test_separation_rejects_stems_not_supported_by_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.local_separation.separation_ready",
        lambda: True,
    )
    with pytest.raises(ValueError, match="不支持这些音轨"):
        LocalSeparator().separate(
            tmp_path / "song.wav",
            tmp_path / "output",
            "htdemucs",
            ["guitar"],
        )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_accompaniment_mix_produces_playable_wav_container(tmp_path: Path) -> None:
    first = tmp_path / "bass.wav"
    second = tmp_path / "drums.wav"
    output = tmp_path / "without-vocals.flac"
    _write_tone(first, 110)
    _write_tone(second, 220)

    LocalSeparator._mix_accompaniment([first, second], output)

    assert output.exists()
    assert output.stat().st_size > 1000


def test_demucs_runner_writes_flac_without_torchcodec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import soundfile
    import torch
    import torchaudio

    monkeypatch.setattr(torchaudio, "save", torchaudio.save)
    _install_soundfile_save()
    output = tmp_path / "stem.flac"
    samples = torch.zeros((2, 441), dtype=torch.float32)
    samples[1, :] = 0.1

    torchaudio.save(
        str(output),
        samples,
        44100,
        encoding="PCM_S",
        bits_per_sample=16,
    )

    info = soundfile.info(str(output))
    assert info.channels == 2
    assert info.samplerate == 44100
    assert info.frames == 441
