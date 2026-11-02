"""Fretboard assignment, quantization and tablature rendering."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from copy import deepcopy
from itertools import product
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


DEFAULT_TUNING = "E2,A2,D3,G3,B3,E4"
SUBDIVISIONS_PER_BEAT = 4
MAX_CHORD_NOTES = 6

PITCH_CLASSES = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}
SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NOTE_RE = re.compile(r"^([A-Ga-g])([#bB]?)(-?\d+)$")


def note_to_midi(value: str) -> int:
    """Convert a scientific pitch name such as E2 or F#4 to MIDI."""
    match = NOTE_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"无效音名: {value}")
    letter, accidental, octave_text = match.groups()
    pitch_class = letter.upper() + accidental.upper()
    if pitch_class not in PITCH_CLASSES:
        raise ValueError(f"无效音名: {value}")
    return 12 * (int(octave_text) + 1) + PITCH_CLASSES[pitch_class]


def midi_to_name(pitch: int) -> str:
    """Convert a MIDI pitch to a readable sharp-name octave."""
    octave = pitch // 12 - 1
    return f"{SHARP_NAMES[pitch % 12]}{octave}"


def parse_tuning(value: str) -> list[int]:
    """Parse six comma-separated low-to-high guitar tuning notes."""
    notes = [part.strip() for part in re.split(r"[,;\s]+", value) if part.strip()]
    if len(notes) != 6:
        raise ValueError("调弦必须包含 6 个音，例如 E2,A2,D3,G3,B3,E4")
    tuning = [note_to_midi(note) for note in notes]
    if any(high <= low for low, high in zip(tuning, tuning[1:])):
        raise ValueError("调弦必须按低音弦到高音弦排列")
    return tuning


def candidates_for_pitch(
    pitch: int,
    tuning: Sequence[int],
    capo: int,
    max_fret: int,
) -> list[tuple[int, int]]:
    """Return playable (string number, fret) pairs for a pitch."""
    result: list[tuple[int, int]] = []
    for tuning_index, open_pitch in enumerate(tuning):
        fret = pitch - open_pitch - capo
        if 0 <= fret <= max_fret:
            # Standard tab convention: 1 is the high E string.
            result.append((6 - tuning_index, fret))
    return sorted(result, key=lambda item: (item[1], abs(item[0] - 3)))


def _assignment_score(assignment: Sequence[dict[str, int]]) -> float:
    frets = [item["fret"] for item in assignment]
    strings = [item["string"] for item in assignment]
    span = max(frets) - min(frets)
    high_fret_cost = sum(max(0, fret - 12) * 3 for fret in frets)
    open_string_cost = sum(0.4 for fret in frets if fret == 0)
    string_cost = sum(abs(string - 3) * 0.08 for string in strings)
    return sum(frets) + span * 1.4 + high_fret_cost + open_string_cost + string_cost


def _best_chord_assignment(
    notes: Sequence[dict[str, Any]],
    tuning: Sequence[int],
    capo: int,
    max_fret: int,
    max_fret_span: int,
) -> tuple[list[tuple[dict[str, Any], dict[str, int]]], list[dict[str, Any]]]:
    candidate_groups = [
        candidates_for_pitch(int(note["pitch"]), tuning, capo, max_fret)[:6]
        for note in notes
    ]
    if any(not candidates for candidates in candidate_groups):
        playable = [
            (note, candidates)
            for note, candidates in zip(notes, candidate_groups)
            if candidates
        ]
        skipped = [
            note for note, candidates in zip(notes, candidate_groups) if not candidates
        ]
    else:
        playable = list(zip(notes, candidate_groups))
        skipped = []

    # Try the full chord first. If no physically reachable fingering exists,
    # remove the weakest detected note and retry instead of generating a chord
    # that spans half the fretboard.
    attempt = list(playable)
    while attempt:
        choices = [
            [candidate for candidate in candidates[:6]]
            for _, candidates in attempt
        ]
        best: list[dict[str, int]] | None = None
        best_score = math.inf
        products: Iterable[tuple[tuple[int, int], ...]] = product(*choices)
        for combination in products:
            strings = [item[0] for item in combination]
            if len(strings) != len(set(strings)):
                continue
            assignment = [
                {"string": string, "fret": fret}
                for string, fret in combination
            ]
            frets = [item["fret"] for item in assignment]
            if max(frets) - min(frets) > max_fret_span:
                continue
            score = _assignment_score(assignment)
            if score < best_score:
                best = assignment
                best_score = score
        if best is not None:
            return list(zip((note for note, _ in attempt), best)), skipped

        weakest = min(
            attempt,
            key=lambda item: float(item[0].get("velocity", 0)),
        )
        skipped.append(weakest[0])
        attempt.remove(weakest)

    return [], skipped


def assign_fretboard(
    notes: list[dict[str, Any]],
    tuning: Sequence[int],
    capo: int,
    max_fret: int,
    max_fret_span: int = 5,
    onset_tolerance: float = 0.08,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Assign pitches to distinct guitar strings for every onset cluster."""
    ordered = sorted(
        (note.copy() for note in notes),
        key=lambda note: (float(note["start"]), -float(note.get("velocity", 0))),
    )
    groups: list[list[dict[str, Any]]] = []
    for note in ordered:
        if not groups or float(note["start"]) - float(groups[-1][0]["start"]) > onset_tolerance:
            groups.append([note])
        else:
            groups[-1].append(note)

    result: list[dict[str, Any]] = []
    warnings: list[str] = []
    skipped_count = 0
    first_skipped_onset: float | None = None
    crowded_count = 0
    first_crowded_onset: float | None = None
    for group in groups:
        # Deduplicate simultaneous detections of the same pitch and keep the
        # strongest six candidates, the maximum a standard guitar can play.
        by_pitch: dict[int, dict[str, Any]] = {}
        for note in group:
            pitch = int(note["pitch"])
            if pitch not in by_pitch or float(note.get("velocity", 0)) > float(
                by_pitch[pitch].get("velocity", 0)
            ):
                by_pitch[pitch] = note
        playable_group = sorted(
            by_pitch.values(),
            key=lambda note: float(note.get("velocity", 0)),
            reverse=True,
        )[:MAX_CHORD_NOTES]
        if len(by_pitch) > MAX_CHORD_NOTES:
            crowded_count += len(by_pitch) - MAX_CHORD_NOTES
            if first_crowded_onset is None:
                first_crowded_onset = float(group[0]["start"])

        assignments, skipped = _best_chord_assignment(
            playable_group,
            tuning,
            capo,
            max_fret,
            max_fret_span,
        )
        for note, assignment in assignments:
            result.append(
                {
                    **note,
                    "string": assignment["string"],
                    "fret": assignment["fret"],
                }
            )
        if skipped:
            skipped_count += len(skipped)
            if first_skipped_onset is None:
                first_skipped_onset = float(group[0]["start"])

    if crowded_count and first_crowded_onset is not None:
        warnings.append(
            f"检测到 {crowded_count} 个无法落在六根弦上的同时音"
            f"（最早 {first_crowded_onset:.2f}s），已保留力度较高的音。"
        )
    if skipped_count and first_skipped_onset is not None:
        warnings.append(
            f"检测到 {skipped_count} 个超出音域或可演奏跨度的音符"
            f"（最早 {first_skipped_onset:.2f}s），已跳过。"
            "可以调整调弦、变调夹、最大品数或和弦跨度。"
        )

    return result, warnings


def quantize_events(
    notes: list[dict[str, Any]],
    bpm: float,
    subdivisions_per_beat: int = SUBDIVISIONS_PER_BEAT,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Quantize note times to a sixteenth-note grid."""
    if bpm <= 0:
        raise ValueError("BPM 必须大于 0")

    step_beats = 1 / subdivisions_per_beat
    seconds_per_beat = 60 / bpm
    quantized: list[dict[str, Any]] = []
    warnings: list[str] = []
    conflict_count = 0
    first_conflict_beat: float | None = None

    for note in notes:
        start_beat = round(
            (float(note["start"]) / seconds_per_beat) / step_beats
        ) * step_beats
        raw_duration = max(0.0, float(note["end"]) - float(note["start"]))
        duration_beats = max(step_beats, round(
            (raw_duration / seconds_per_beat) / step_beats
        ) * step_beats)
        quantized.append(
            {
                **note,
                "start_beat": round(start_beat, 4),
                "duration_beats": round(duration_beats, 4),
                "pitch_name": midi_to_name(int(note["pitch"])),
                "velocity": int(round(float(note.get("velocity", 0.8)) * 127)),
            }
        )

    # Two notes cannot begin at the same grid slot on the same string.
    occupied: dict[tuple[int, float], dict[str, Any]] = {}
    deduplicated: list[dict[str, Any]] = []
    for note in sorted(
        quantized,
        key=lambda item: (
            item["start_beat"],
            item["string"],
            -int(item["velocity"]),
        ),
    ):
        key = (int(note["string"]), float(note["start_beat"]))
        if key in occupied:
            conflict_count += 1
            if first_conflict_beat is None:
                first_conflict_beat = float(note["start_beat"])
            continue
        occupied[key] = note
        deduplicated.append(note)

    deduplicated.sort(key=lambda item: (item["start_beat"], item["string"]))
    if conflict_count and first_conflict_beat is not None:
        warnings.append(
            f"有 {conflict_count} 个音在十六分音符网格上发生同弦冲突"
            f"（最早 {first_conflict_beat:.2f} 拍），已保留力度较高的音。"
        )
    return deduplicated, warnings


def render_ascii_tab(
    events: Sequence[dict[str, Any]],
    bpm: float,
    tuning_text: str,
    capo: int,
    subdivisions_per_beat: int = SUBDIVISIONS_PER_BEAT,
    beats_per_measure: int = 4,
) -> str:
    """Render a compact six-line ASCII guitar tab."""
    steps_per_measure = subdivisions_per_beat * beats_per_measure
    max_step = max(
        (
            int(round(float(event["start_beat"]) * subdivisions_per_beat))
            for event in events
        ),
        default=0,
    )
    measure_count = max(1, math.ceil((max_step + 1) / steps_per_measure))
    width = measure_count * steps_per_measure
    rows = {string: ["---"] * width for string in range(1, 7)}

    for event in events:
        step = int(round(float(event["start_beat"]) * subdivisions_per_beat))
        if 0 <= step < width:
            rows[int(event["string"])][step] = f"{int(event['fret']):>2}-"

    header_parts = []
    for measure in range(measure_count):
        header_parts.append(f"M{measure + 1}".ljust(steps_per_measure * 3 - 1) + "|")

    lines = [
        f"Guitar Tab  BPM: {bpm:g}  Capo: {capo}",
        f"Tuning (low to high): {tuning_text}",
        "".ljust(3) + "".join(header_parts),
    ]
    for string in range(1, 7):
        measure_text: list[str] = []
        for measure in range(measure_count):
            start = measure * steps_per_measure
            end = start + steps_per_measure
            measure_text.append("".join(rows[string][start:end]) + "|")
        lines.append(f"{string}|" + "".join(measure_text))
    return "\n".join(lines)


def write_musicxml(
    events: Sequence[dict[str, Any]],
    bpm: float,
    output_path: Path,
    title: str,
    tuning_text: str = DEFAULT_TUNING,
) -> None:
    """Export a guitar part with string and fret indications."""
    from music21 import articulations, chord, clef, instrument, meter, stream, tempo

    score = stream.Score(id="guitar-transcription")
    score.insert(0, metadata_title(title))
    part = stream.Part(id="guitar")
    part.insert(0, instrument.Guitar())
    part.insert(0, clef.TabClef())
    part.insert(0, meter.TimeSignature("4/4"))
    part.insert(0, tempo.MetronomeMark(number=bpm))

    grouped: dict[float, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(float(event["start_beat"]), []).append(event)

    for start_beat, group in sorted(grouped.items()):
        music_chord = chord.Chord([int(item["pitch"]) for item in group])
        music_chord.quarterLength = max(
            float(item["duration_beats"]) for item in group
        )
        for music_note, event in zip(music_chord.notes, group):
            music_note.volume.velocity = int(event["velocity"])
            music_note.articulations.append(
                articulations.StringIndication(int(event["string"]))
            )
            music_note.articulations.append(
                articulations.FretIndication(int(event["fret"]))
            )
        part.insert(start_beat, music_chord)

    part.makeMeasures(inPlace=True)
    score.insert(0, part)
    score.write("musicxml", fp=str(output_path))
    _add_musicxml_technical_indications(output_path, events, tuning_text)


def _musicxml_pitch_midi(note_element: ET.Element) -> int | None:
    pitch = note_element.find("pitch")
    if pitch is None:
        return None
    step = pitch.findtext("step")
    octave_text = pitch.findtext("octave")
    if step is None or octave_text is None:
        return None
    alter = int(pitch.findtext("alter", "0"))
    base = PITCH_CLASSES.get(step.upper())
    if base is None:
        return None
    return 12 * (int(octave_text) + 1) + base + alter


def _add_musicxml_technical_indications(
    output_path: Path,
    events: Sequence[dict[str, Any]],
    tuning_text: str,
) -> None:
    """Add string/fret technical data that music21 does not serialize."""
    tree = ET.parse(output_path)
    root = tree.getroot()

    first_attributes = root.find(".//part/measure/attributes")
    if first_attributes is not None and first_attributes.find("staff-details") is None:
        staff_details = ET.SubElement(first_attributes, "staff-details")
        ET.SubElement(staff_details, "staff-lines").text = "6"
        for line, pitch in enumerate(reversed(parse_tuning(tuning_text)), start=1):
            pitch_name = midi_to_name(pitch)
            match = re.fullmatch(r"([A-G])(#?)(-?\d+)", pitch_name)
            if match is None:
                continue
            step, accidental, octave = match.groups()
            tuning = ET.SubElement(staff_details, "staff-tuning", line=str(line))
            ET.SubElement(tuning, "tuning-step").text = step
            if accidental:
                ET.SubElement(tuning, "tuning-alter").text = "1"
            ET.SubElement(tuning, "tuning-octave").text = octave

    by_pitch: defaultdict[int, deque[dict[str, Any]]] = defaultdict(deque)
    for event in sorted(events, key=lambda item: (float(item["start_beat"]), int(item["pitch"]))):
        by_pitch[int(event["pitch"])].append(event)

    for note_element in root.findall(".//part/measure/note"):
        midi_pitch = _musicxml_pitch_midi(note_element)
        if midi_pitch is None or not by_pitch[midi_pitch]:
            continue
        event = by_pitch[midi_pitch].popleft()
        notations = note_element.find("notations")
        if notations is None:
            notations = ET.SubElement(note_element, "notations")
        technical = notations.find("technical")
        if technical is None:
            technical = ET.SubElement(notations, "technical")
        ET.SubElement(technical, "string").text = str(int(event["string"]))
        ET.SubElement(technical, "fret").text = str(int(event["fret"]))

    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def metadata_title(title: str):
    """Small indirection that keeps music21 imports local."""
    from music21 import metadata

    return metadata.Metadata(title=title)


def build_tablature(
    raw_notes: list[dict[str, Any]],
    bpm: float,
    tuning_text: str,
    capo: int,
    max_fret: int,
    max_fret_span: int = 5,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run fretboard assignment and quantization as one pure operation."""
    tuning = parse_tuning(tuning_text)
    assigned, assignment_warnings = assign_fretboard(
        raw_notes,
        tuning,
        capo,
        max_fret,
        max_fret_span=max_fret_span,
    )
    events, quantization_warnings = quantize_events(assigned, bpm)
    return events, assignment_warnings + quantization_warnings


def make_tab_text(
    events: Sequence[dict[str, Any]],
    bpm: float,
    tuning_text: str,
    capo: int,
) -> str:
    return render_ascii_tab(events, bpm, tuning_text, capo)


def write_midi(
    events: Sequence[dict[str, Any]],
    bpm: float,
    output_path: Path,
) -> None:
    """Write the same playable note events used by the tablature."""
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    guitar = pretty_midi.Instrument(program=25, name="Guitar")
    seconds_per_beat = 60 / bpm
    for event in sorted(events, key=lambda item: float(item["start_beat"])):
        start = max(0.0, float(event["start_beat"]) * seconds_per_beat)
        end = start + max(
            0.03,
            float(event["duration_beats"]) * seconds_per_beat,
        )
        guitar.notes.append(
            pretty_midi.Note(
                velocity=max(1, min(127, int(event.get("velocity", 80)))),
                pitch=int(event["pitch"]),
                start=start,
                end=end,
            )
        )
    midi.instruments.append(guitar)
    midi.write(str(output_path))


def combine_musicxml(
    parts: Sequence[tuple[str, str, Path]],
    output_path: Path,
    title: str,
    capo: int = 0,
) -> None:
    """Combine separately rendered guitar parts into one multi-track score."""
    if not parts:
        raise ValueError("没有可合并的吉他 MusicXML")

    roots = [ET.parse(path).getroot() for _, _, path in parts]
    root = deepcopy(roots[0])
    part_list = root.find("part-list")
    if part_list is None:
        part_list = ET.Element("part-list")
        root.insert(0, part_list)
    for child in list(part_list):
        part_list.remove(child)
    for part in list(root.findall("part")):
        root.remove(part)

    work_title = root.find("./work/work-title")
    if work_title is not None:
        work_title.text = title
    movement_title = root.find("movement-title")
    if movement_title is not None:
        movement_title.text = title
    creator = root.find("./identification/creator")
    if creator is not None:
        creator.text = "Fretline"

    for index, ((key, label, _), source_root) in enumerate(
        zip(parts, roots),
        start=1,
    ):
        suffix = f"-{key}"
        source_part_list = source_root.find("part-list")
        source_part = source_root.find("part")
        if source_part_list is None or source_part is None:
            continue

        score_part = source_part_list.find("score-part")
        if score_part is None:
            continue
        score_part = deepcopy(score_part)
        part_id = f"P{index}"
        score_part.set("id", part_id)
        for node in score_part.iter():
            node_id = node.get("id")
            if node_id and node is not score_part:
                node.set("id", f"{node_id}{suffix}")
        part_name = score_part.find("part-name")
        if part_name is not None:
            part_name.text = label
        abbreviation = score_part.find("part-abbreviation")
        if abbreviation is not None:
            abbreviation.text = label
        part_list.append(score_part)

        combined_part = deepcopy(source_part)
        combined_part.set("id", part_id)
        if capo > 0:
            first_measure = combined_part.find("measure")
            if first_measure is not None:
                direction = ET.Element("direction", placement="above")
                direction_type = ET.SubElement(direction, "direction-type")
                words = ET.SubElement(direction_type, "words")
                words.text = f"Capo fret {capo}"
                first_measure.insert(0, direction)
        root.append(combined_part)

    ET.ElementTree(root).write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )

