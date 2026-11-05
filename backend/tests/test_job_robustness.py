from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import jobs
from app import main
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


def test_recent_jobs_api_returns_modes_in_update_order(monkeypatch) -> None:
    newer = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    older = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
    song_job = SongTranscriptionJob(
        id="song-job",
        filename="电动少女.mp3",
        status="running",
        progress=25,
        stage="separating",
        message="正在分离",
        created_at=older,
        updated_at=newer,
        options=TranscriptionOptions(bpm=120),
        revision=2,
    )
    separation_job = jobs.SeparationJob(
        id="separation-job",
        filename="开始懂了.mp3",
        status="succeeded",
        progress=100,
        stage="completed",
        message="分离完成",
        created_at=older,
        updated_at=older,
        options=SeparationOptions(remove_stems=["vocals"]),
        result={
            "title": "开始懂了",
            "model": {"key": "htdemucs", "label": "HTDemucs 4 轨"},
            "device": "cuda",
            "quality": "balanced",
            "duration_seconds": 281.0,
            "stems": [],
            "accompaniments": [],
            "warnings": [],
            "archive_filename": None,
        },
        revision=4,
    )
    monkeypatch.setattr(main.song_runner, "recent", lambda limit: [song_job])
    monkeypatch.setattr(
        main.separation_runner,
        "recent",
        lambda limit: [separation_job],
    )
    monkeypatch.setattr(main.runner, "recent", lambda limit: [])

    with TestClient(main.app) as client:
        response = client.get("/api/jobs/recent?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["jobs"]] == [
        "song-job",
        "separation-job",
    ]
    assert [item["mode"] for item in payload["jobs"]] == ["song", "separate"]
    assert payload["jobs"][1]["result_title"] == "开始懂了"
