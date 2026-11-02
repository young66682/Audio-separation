from __future__ import annotations

from pathlib import Path
from time import sleep
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import main
from app.song_transcriber import SongPipelineOutcome, SongTranscriber


def _fake_song_transcription(
    self,
    audio_path: Path,
    output_dir: Path,
    original_filename: str,
    options,
    progress_callback=None,
):
    stems_dir = output_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    (stems_dir / "lead.flac").write_bytes(b"lead")
    (stems_dir / "rhythm.flac").write_bytes(b"rhythm")
    (stems_dir / "backing.flac").write_bytes(b"backing")

    guitars = []
    for key, label in (("lead", "主音吉他"), ("rhythm", "节奏吉他")):
        guitar_dir = output_dir / "guitars" / key
        guitar_dir.mkdir(parents=True, exist_ok=True)
        tab_path = guitar_dir / "guitar-tab.txt"
        tab_path.write_text(f"{label}\n", encoding="utf-8")
        transcription = {
            "title": original_filename,
            "bpm": 120,
            "tuning": "E2,A2,D3,G3,B3,E4",
            "capo": 0,
            "max_fret": 22,
            "note_count": 1,
            "raw_note_count": 1,
            "events": [],
            "warnings": [],
            "tab_text": "1|--0--|",
            "artifacts": {"tab": "guitar-tab.txt"},
        }
        guitars.append(
            {
                "key": key,
                "label": label,
                "audio_format": "flac",
                "transcription": transcription,
                "error": None,
            }
        )
    archive_path = output_dir / "song-guitar-tabs.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("tab.txt", "1|--0--|")
    progress_callback and progress_callback(100, "completed", "done")
    return SongPipelineOutcome(
        status="succeeded",
        result={
            "title": "song",
            "bpm": 120,
            "source": "mvsep-lead-rhythm",
            "guitars": guitars,
            "backing_available": True,
            "warnings": [],
        },
    )


def test_song_transcription_api_flow(monkeypatch) -> None:
    monkeypatch.setattr(main, "MVSEP_API_TOKEN", "test-token")
    monkeypatch.setattr(
        SongTranscriber,
        "transcribe",
        _fake_song_transcription,
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/song-transcriptions",
            files={"audio": ("song.wav", b"fake audio", "audio/wav")},
            data={"bpm": "120"},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        job = None
        for _ in range(40):
            job = client.get(f"/api/song-transcriptions/{job_id}").json()
            if job["status"] in {"succeeded", "partial", "failed"}:
                break
            sleep(0.05)

        assert job is not None
        assert job["status"] == "succeeded"
        assert len(job["result"]["guitars"]) == 2
        assert client.get(
            f"/api/song-transcriptions/{job_id}/audio/lead"
        ).status_code == 200
        assert client.get(
            f"/api/song-transcriptions/{job_id}/guitars/lead/artifacts/tab"
        ).status_code == 200
        assert client.get(
            f"/api/song-transcriptions/{job_id}/archive"
        ).status_code == 200
