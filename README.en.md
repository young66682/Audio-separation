# Fretline

Fretline is a local-first FastAPI and Vue workspace for stem separation, custom
instrumental accompaniment, and guitar transcription.

## Features

- Local Demucs separation with four- and six-stem models.
- Isolated vocals, drums, bass, guitar, piano, and other instruments.
- Select any instrument to create an accompaniment that removes it.
- Batch ZIP export with stems, accompaniments, manifest, and source audio.
- Local guitar transcription to tablature, MIDI, MusicXML, and JSON.
- Optional MVSEP lead/rhythm dual-guitar transcription.
- Automatic CPU, CUDA, and Apple MPS device selection.

## Quick start

Requirements: Python 3.11, Node.js 20+, uv, FFmpeg, and ffprobe in `PATH`.

```powershell
.\setup.ps1
.\start.ps1
```

Open <http://127.0.0.1:8000>. Model weights are downloaded on first use and
cached for later offline runs.

For UI development:

```powershell
cd frontend
npm run dev
```

## Accompaniment behavior

Removing an instrument means separating the remaining stems and mixing them
back together. It is not perfect phase cancellation; bleed can remain with
distorted instruments, reverb, or overlapping stereo positions.

See [README.md](README.md) for model selection, configuration, API endpoints,
testing, and output paths.
