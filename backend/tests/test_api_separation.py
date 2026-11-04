from __future__ import annotations

from pathlib import Path
from time import sleep
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import main
from app.local_separation import LocalSeparator


def _fake_separate(
    self,
    audio_path: Path,
    output_dir: Path,
    model_name: str,
    remove_stems: list[str],
    quality: str = "balanced",
    progress_callback=None,
    title: str | None = None,
):
    stems_dir = output_dir / "stems"
    accompaniment_dir = output_dir / "accompaniments"
    stems_dir.mkdir(parents=True, exist_ok=True)
    accompaniment_dir.mkdir(parents=True, exist_ok=True)
    model = main.SEPARATION_MODELS[model_name]
    for stem in model.stems:
        (stems_dir / f"{stem}.flac").write_bytes(stem.encode())
    for stem in remove_stems:
        (accompaniment_dir / f"without-{stem}.flac").write_bytes(
            f"without-{stem}".encode()
        )
    archive_path = output_dir / "song-stems.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", "{}")
    if progress_callback:
        progress_callback(100, "archiving", "done")
    stem_labels = {
        "vocals": "人声",
        "drums": "鼓组",
        "bass": "贝斯",
        "guitar": "吉他",
        "piano": "钢琴",
        "other": "其他乐器",
    }
    return {
        "title": Path(title).stem if title else "song",
        "model": {"key": model.key, "label": model.label},
        "device": "cpu",
        "quality": quality,
        "duration_seconds": 42,
        "stems": [
            {
                "key": stem,
                "label": stem_labels[stem],
                "filename": f"{stem}.flac",
                "audio_format": "flac",
            }
            for stem in model.stems
        ],
        "accompaniments": [
            {
                "key": stem,
                "label": f"去掉{stem_labels[stem]}的伴奏",
                "removed_stem": stem,
                "removed_label": stem_labels[stem],
                "filename": f"without-{stem}.flac",
                "audio_format": "flac",
            }
            for stem in remove_stems
        ],
        "warnings": [],
        "archive_filename": archive_path.name,
    }


def test_separation_api_flow(monkeypatch) -> None:
    monkeypatch.setattr(main, "separation_ready", lambda: True)
    monkeypatch.setattr(LocalSeparator, "separate", _fake_separate)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/separations",
            files={"audio": ("song.wav", b"fake audio", "audio/wav")},
            data={
                "model": "htdemucs_6s",
                "remove_stems": "guitar,piano",
                "quality": "fast",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        job = None
        for _ in range(60):
            job = client.get(f"/api/separations/{job_id}").json()
            if job["status"] in {"succeeded", "failed"}:
                break
            sleep(0.05)

        assert job is not None
        assert job["status"] == "succeeded", job.get("error")
        assert len(job["result"]["stems"]) == 6
        assert [
            item["removed_stem"] for item in job["result"]["accompaniments"]
        ] == ["guitar", "piano"]
        assert client.get(
            f"/api/separations/{job_id}/audio/source"
        ).status_code == 200
        assert client.get(
            f"/api/separations/{job_id}/audio/stem/guitar"
        ).content == b"guitar"
        assert client.get(
            f"/api/separations/{job_id}/audio/accompaniment/piano"
        ).content == b"without-piano"
        assert client.get(f"/api/separations/{job_id}/archive").status_code == 200


def test_separation_api_rejects_unsupported_stem(monkeypatch) -> None:
    monkeypatch.setattr(main, "separation_ready", lambda: True)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/separations",
            files={"audio": ("song.wav", b"fake audio", "audio/wav")},
            data={
                "model": "htdemucs",
                "remove_stems": "guitar",
                "quality": "balanced",
            },
        )

    assert response.status_code == 422
    assert "不支持" in response.json()["detail"]
