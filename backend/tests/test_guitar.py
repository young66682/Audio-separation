from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.guitar import (
    build_tablature,
    candidates_for_pitch,
    combine_musicxml,
    make_tab_text,
    midi_to_name,
    parse_tuning,
    write_midi,
    write_musicxml,
)


STANDARD_TUNING = "E2,A2,D3,G3,B3,E4"


def note(start: float, end: float, pitch: int, velocity: float = 0.8):
    return {
        "start": start,
        "end": end,
        "pitch": pitch,
        "velocity": velocity,
    }


def test_pitch_and_tuning_helpers() -> None:
    assert midi_to_name(64) == "E4"
    assert parse_tuning(STANDARD_TUNING) == [40, 45, 50, 55, 59, 64]
    assert candidates_for_pitch(64, parse_tuning(STANDARD_TUNING), 0, 22)[0] == (
        1,
        0,
    )


def test_invalid_tuning_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_tuning("E2,A2,D3")
    with pytest.raises(ValueError):
        parse_tuning("E2,D3,A2,G3,B3,E4")


def test_simultaneous_notes_use_distinct_strings() -> None:
    events, warnings = build_tablature(
        [
            note(0.0, 1.0, 52),
            note(0.01, 1.1, 59),
            note(0.02, 1.2, 64),
        ],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )

    assert len(events) == 3
    assert len({event["string"] for event in events}) == 3
    assert warnings == []
    assert all(0 <= event["fret"] <= 22 for event in events)


def test_unplayable_notes_are_skipped_with_warning() -> None:
    events, warnings = build_tablature(
        [note(0.0, 1.0, 30), note(0.01, 1.0, 64)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )

    assert len(events) == 1
    assert events[0]["pitch"] == 64
    assert any("超出音域或可演奏跨度" in warning for warning in warnings)


def test_chord_span_is_reduced_to_playable_shape() -> None:
    events, warnings = build_tablature(
        [note(0.0, 1.0, 40, 0.9), note(0.01, 1.0, 76, 0.35)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=24,
        max_fret_span=5,
    )

    assert len(events) == 1
    assert events[0]["pitch"] == 40
    assert any("超出音域或可演奏跨度" in warning for warning in warnings)


def test_tab_quantizes_to_sixteenth_notes_and_renders_six_lines() -> None:
    events, _ = build_tablature(
        [note(0.0, 0.30, 64), note(0.51, 0.75, 67)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )
    tab = make_tab_text(events, 120, STANDARD_TUNING, 0)
    string_lines = [line for line in tab.splitlines() if line[:2] in {"1|", "2|", "3|", "4|", "5|", "6|"}]

    assert len(string_lines) == 6
    assert events[0]["start_beat"] == 0
    assert events[1]["start_beat"] == 1


def test_musicxml_contains_string_and_fret_indications(tmp_path: Path) -> None:
    events, _ = build_tablature(
        [note(0.0, 0.5, 64), note(0.51, 1.0, 67)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )
    output = tmp_path / "guitar.musicxml"
    write_musicxml(events, 120, output, "Test transcription")
    xml = output.read_text(encoding="utf-8")

    assert "<score-partwise" in xml
    assert "<string>" in xml
    assert "<fret>" in xml


def test_musicxml_keeps_overlapping_attacks_in_complete_measures(
    tmp_path: Path,
) -> None:
    events, _ = build_tablature(
        [
            note(0.0, 2.0, 64),
            note(0.25, 2.25, 67),
            note(0.5, 2.5, 71),
            note(1.0, 3.0, 72),
        ],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )
    output = tmp_path / "overlap.musicxml"
    write_musicxml(events, 120, output, "Overlap")

    root = ET.parse(output).getroot()
    divisions = int(root.findtext("./part/measure/attributes/divisions"))
    for measure in root.findall("./part/measure"):
        duration = sum(
            int(note.findtext("duration", "0"))
            for note in measure.findall("note")
            if note.find("chord") is None
        )
        assert duration == divisions * 4


def test_midi_uses_final_tab_events(tmp_path: Path) -> None:
    events, _ = build_tablature(
        [note(0.0, 0.5, 64), note(0.51, 1.0, 67)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )
    output = tmp_path / "guitar.mid"
    write_midi(events, 120, output)

    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(output))
    assert len(midi.instruments[0].notes) == len(events)


def test_combined_musicxml_contains_two_guitar_parts(tmp_path: Path) -> None:
    lead_events, _ = build_tablature(
        [note(0.0, 0.5, 64)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )
    rhythm_events, _ = build_tablature(
        [note(0.0, 0.5, 52), note(0.51, 1.0, 59)],
        bpm=120,
        tuning_text=STANDARD_TUNING,
        capo=0,
        max_fret=22,
    )
    lead_path = tmp_path / "lead.musicxml"
    rhythm_path = tmp_path / "rhythm.musicxml"
    combined_path = tmp_path / "guitar-score.musicxml"
    write_musicxml(lead_events, 120, lead_path, "Lead")
    write_musicxml(rhythm_events, 120, rhythm_path, "Rhythm")
    combine_musicxml(
        [("lead", "Lead Guitar", lead_path), ("rhythm", "Rhythm Guitar", rhythm_path)],
        combined_path,
        "Test Song",
        capo=2,
    )

    root = ET.parse(combined_path).getroot()
    assert len(root.findall("part")) == 2
    assert [item.text for item in root.findall("./part-list/score-part/part-name")] == [
        "Lead Guitar",
        "Rhythm Guitar",
    ]
    assert [
        item.text for item in root.findall(".//midi-channel")
    ] == ["1", "2"]
    assert "Capo fret 2" in combined_path.read_text(encoding="utf-8")
    first_measure = root.find("./part/measure")
    assert first_measure is not None
    assert [child.tag for child in first_measure][:2] == [
        "attributes",
        "direction",
    ]

