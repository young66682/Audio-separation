Based on the provided code map, I can see this is an audio source separation project. Let me create a comprehensive README for it:

# Audio Separation

A professional audio source separation tool that uses deep learning (Demucs) to extract individual stems from audio files.

## Features

- **Stem Separation**: Separate audio into multiple stems (vocals, drums, bass, other)
- **Multiple Model Support**: Support for various Demucs models (default: htdemucs)
- **MP3 Export**: Convert separated tracks to MP3 format with configurable bitrate
- **User-Friendly Interface**: Built with Streamlit for easy interaction
- **Progress Tracking**: Real-time progress display during separation

## Installation

1. Clone the repository:
```bash
git clone https://gitee.com/zhaoy515/audio_separation.git
cd audio_separation
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install FFmpeg (required for MP3 conversion):
- **Ubuntu/Debian**: `sudo apt install ffmpeg`
- **macOS**: `brew install ffmpeg`
- **Windows**: Download from [FFmpeg website](https://ffmpeg.org/download.html)

## Usage

Run the application:
```bash
streamlit run mainService.py
```

Or directly:
```bash
python mainService.py
```

### Using the Web Interface

1. Select an audio file (WAV, MP3, FLAC, etc.)
2. Choose the stems you want to extract
3. Select the model (default: htdemucs)
4. Click "Start Separation"
5. Download the separated stems

### Programmatic Usage

```python
from mainService import StemSeparator, MP3Exporter
from pathlib import Path

# Separate audio into stems
separator = StemSeparator(model_name="htdemucs")
results = separator.separate(
    input_file=Path("input.wav"),
    selected_stems=["vocals", "drums", "bass", "other"],
    output_dir=Path("output")
)

# Convert to MP3
exporter = MP3Exporter(output_dir="output", bitrate=192)
mp3_path = exporter.convert_to_mp3(results["vocals"], "vocals")
```

## Available Stems

- **Vocals**: Vocal tracks
- **Drums**: Drum/percussion tracks
- **Bass**: Bass tracks
- **Other**: Other instruments

## Requirements

See `requirements.txt` for full dependency list. Key dependencies:
- demucs (audio source separation)
- streamlit (web interface)
- ffmpeg-python (MP3 conversion)

## License

See the `LICENSE` file for details.

## Acknowledgments

- [Demucs](https://github.com/facebookresearch/demucs) - Deep audio separation model
- [FFmpeg](https://ffmpeg.org/) - Audio format conversion