from __future__ import annotations

from pathlib import Path

from app.mvsep import SeparationResult
from app.schemas import TranscriptionOptions
from app.song_transcriber import SongTranscriber


class FakeSeparator:
    def separate(self, audio_path: Path, output_dir: Path, progress_callback=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        lead = output_dir / "lead.flac"
        rhythm = output_dir / "rhythm.flac"
        backing = output_dir / "backing.flac"
        lead.write_bytes(b"lead")
        rhythm.write_bytes(b"rhythm")
        backing.write_bytes(b"backing")
        if progress_callback:
            progress_callback(55, "分离完成")
        return SeparationResult(lead=lead, rhythm=rhythm, backing=backing)


class FakeTranscriber:
    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        original_filename: str,
        options: TranscriptionOptions,
        progress_callback=None,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        tab = output_dir / "guitar-tab.txt"
        tab.write_text(f"lead={audio_path.parent.name}\n", encoding="utf-8")
        if progress_callback:
            progress_callback(100, "completed", "done")
        return {
            "title": original_filename,
            "bpm": options.bpm,
            "tuning": options.tuning,
            "capo": options.capo,
            "max_fret": options.max_fret,
            "note_count": 3,
            "raw_note_count": 3,
            "events": [],
            "warnings": [],
            "tab_text": "E|---0---|",
            "artifacts": {"tab": "guitar-tab.txt"},
        }


def test_song_pipeline_transcribes_both_guitars(tmp_path: Path) -> None:
    audio = tmp_path / "full-song.wav"
    audio.write_bytes(b"fake")
    outcome = SongTranscriber(
        transcriber=FakeTranscriber(),
        separator=FakeSeparator(),
    ).transcribe(
        audio,
        tmp_path / "output",
        "full-song.wav",
        TranscriptionOptions(bpm=120),
    )

    assert outcome.status == "succeeded"
    assert [item["key"] for item in outcome.result["guitars"]] == [
        "lead",
        "rhythm",
    ]
    assert all(
        item["transcription"] is not None
        for item in outcome.result["guitars"]
    )
    archive = next((tmp_path / "output").glob("*-guitar-tabs.zip"))
    assert archive.stat().st_size > 0

