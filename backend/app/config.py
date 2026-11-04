"""运行时目录、模型配置与上传限制。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = Path(os.getenv("GUITAR_TAB_DATA_DIR", BACKEND_DIR / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
SONG_JOBS_DIR = JOBS_DIR / "songs"
SEPARATION_JOBS_DIR = JOBS_DIR / "separations"
FRONTEND_DIST_DIR = PROJECT_DIR / "frontend" / "dist"

ALLOWED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".ogg",
    ".aiff",
    ".aif",
}
DEFAULT_MAX_UPLOAD_MB = 100
MAX_UPLOAD_BYTES = int(
    os.getenv("GUITAR_TAB_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB))
) * 1024 * 1024

MVSEP_API_URL = os.getenv("MVSEP_API_URL", "https://mvsep.com/api").rstrip("/")
MVSEP_API_TOKEN = os.getenv("MVSEP_API_TOKEN", "").strip()
MVSEP_SEPARATION_TYPE = os.getenv("MVSEP_SEPARATION_TYPE", "101")
MVSEP_MODEL_TYPE = os.getenv("MVSEP_MODEL_TYPE", "1")
MVSEP_OUTPUT_FORMAT = os.getenv("MVSEP_OUTPUT_FORMAT", "2")
MVSEP_WORKFLOW = os.getenv("MVSEP_WORKFLOW", "guitar_first")
MVSEP_POLL_INTERVAL_SECONDS = float(
    os.getenv("MVSEP_POLL_INTERVAL_SECONDS", "3")
)
MVSEP_JOB_TIMEOUT_SECONDS = int(os.getenv("MVSEP_JOB_TIMEOUT_SECONDS", "3600"))
MVSEP_USE_ENV_PROXY = os.getenv("MVSEP_USE_ENV_PROXY", "false").lower() in {
    "1",
    "true",
    "yes",
}

DEMUCS_DEVICE = os.getenv("DEMUCS_DEVICE", "auto").strip().lower()
DEMUCS_JOB_TIMEOUT_SECONDS = int(
    os.getenv("DEMUCS_JOB_TIMEOUT_SECONDS", "7200")
)


def ensure_runtime_directories() -> None:
    """创建本地任务运行器所需的目录。"""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    SONG_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    SEPARATION_JOBS_DIR.mkdir(parents=True, exist_ok=True)

