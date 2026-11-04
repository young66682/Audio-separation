from __future__ import annotations

from pathlib import Path

from app import jobs
from app.schemas import (
    SeparationOptions,
    SongTranscriptionJob,
    TranscriptionOptions,
)


def test_song_job_retry_reuses_existing_input(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "SONG_JOBS_DIR", tmp_path)
    runner = jobs.SongJobRunner()
    job = runner.new_job(
        "song.wav",
        TranscriptionOptions(bpm=120),
    )
    job_dir = runner.job_dir(job.id)
    (job_dir / "input.wav").write_bytes(b"input")
    runner._update(
        job.id,
        status="failed",
        stage="failed",
        error="download failed",
    )
    submitted: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        runner,
        "start",
        lambda job_id, path: submitted.append((job_id, path)),
    )

    retried = runner.retry(job.id)

    assert retried.status == "queued"
    assert retried.error is None
    assert submitted == [(job.id, job_dir / "input.wav")]
    runner.shutdown()


def test_job_snapshot_survives_runner_restart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "SONG_JOBS_DIR", tmp_path)
    first = jobs.SongJobRunner()
    job = first.new_job(
        "song.wav",
        TranscriptionOptions(bpm=100),
    )
    first._update(
        job.id,
        status="failed",
        stage="failed",
        error="network error",
    )
    first.shutdown()

    second = jobs.SongJobRunner()
    restored = second.get(job.id)

    assert isinstance(restored, SongTranscriptionJob)
    assert restored.status == "failed"
    assert restored.error == "network error"
    assert restored.options.bpm == 100
    second.shutdown()
