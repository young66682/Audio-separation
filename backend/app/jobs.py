"""Thread-backed local transcription job store."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import JOBS_DIR, SONG_JOBS_DIR
from .schemas import (
    SongTranscriptionJob,
    TranscriptionJob,
    TranscriptionOptions,
)
from .song_transcriber import SongTranscriber
from .transcriber import GuitarTranscriber


class UnknownJobError(KeyError):
    """Raised when a job id is not present in the current process."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobRunner:
    """Run one transcription at a time and expose progress snapshots."""

    def __init__(self) -> None:
        self._jobs: dict[str, TranscriptionJob] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="guitar-transcriber",
        )
        self._transcriber = GuitarTranscriber()

    def new_job(
        self,
        filename: str,
        options: TranscriptionOptions,
    ) -> TranscriptionJob:
        now = _utc_now()
        job = TranscriptionJob(
            id=uuid.uuid4().hex,
            filename=filename,
            status="queued",
            progress=0,
            stage="queued",
            message="任务已进入队列",
            created_at=now,
            updated_at=now,
            options=options,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def job_dir(self, job_id: str) -> Path:
        job = self.get(job_id)
        directory = JOBS_DIR / job.id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def start(self, job_id: str, audio_path: Path) -> None:
        job = self.get(job_id)
        output_dir = self.job_dir(job_id)
        self._executor.submit(
            self._run,
            job_id,
            audio_path,
            output_dir,
            job.filename,
            job.options,
        )

    def fail_upload(self, job_id: str, message: str) -> None:
        self._update(
            job_id,
            status="failed",
            progress=0,
            stage="failed",
            message="上传失败",
            error=message,
        )

    def _run(
        self,
        job_id: str,
        audio_path: Path,
        output_dir: Path,
        filename: str,
        options: TranscriptionOptions,
    ) -> None:
        self._update(
            job_id,
            status="running",
            progress=1,
            stage="starting",
            message="开始转录",
            error=None,
        )

        def progress(progress_value: int, stage: str, message: str) -> None:
            self._update(
                job_id,
                progress=progress_value,
                stage=stage,
                message=message,
            )

        try:
            result = self._transcriber.transcribe(
                audio_path,
                output_dir,
                filename,
                options,
                progress,
            )
            self._update(
                job_id,
                status="succeeded",
                progress=100,
                stage="completed",
                message="转录完成",
                result=result,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="failed",
                message="转录失败",
                error=str(exc),
            )

    def _update(self, job_id: str, **changes: Any) -> TranscriptionJob:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                raise UnknownJobError(job_id)
            payload = current.model_dump(mode="python")
            payload.update(
                {
                    **changes,
                    "updated_at": _utc_now(),
                    "revision": current.revision + 1,
                }
            )
            updated = TranscriptionJob.model_validate(payload)
            self._jobs[job_id] = updated
            return updated

    def get(self, job_id: str) -> TranscriptionJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise UnknownJobError(job_id)
            return job.model_copy(deep=True)

    @staticmethod
    def artifact_filename(artifact_key: str) -> str | None:
        return GuitarTranscriber.artifacts.get(artifact_key)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class SongJobRunner:
    """Run one full-song dual-guitar job at a time."""

    def __init__(self) -> None:
        self._jobs: dict[str, SongTranscriptionJob] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="song-guitar-transcriber",
        )

    def new_job(
        self,
        filename: str,
        options: TranscriptionOptions,
    ) -> SongTranscriptionJob:
        now = _utc_now()
        job = SongTranscriptionJob(
            id=uuid.uuid4().hex,
            filename=filename,
            status="queued",
            progress=0,
            stage="queued",
            message="整曲任务已进入队列",
            created_at=now,
            updated_at=now,
            options=options,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def job_dir(self, job_id: str) -> Path:
        job = self.get(job_id)
        directory = SONG_JOBS_DIR / job.id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def start(self, job_id: str, audio_path: Path) -> None:
        job = self.get(job_id)
        self._executor.submit(
            self._run,
            job_id,
            audio_path,
            self.job_dir(job_id),
            job.filename,
            job.options,
        )

    def fail_upload(self, job_id: str, message: str) -> None:
        self._update(
            job_id,
            status="failed",
            progress=0,
            stage="failed",
            message="上传失败",
            error=message,
        )

    def _run(
        self,
        job_id: str,
        audio_path: Path,
        output_dir: Path,
        filename: str,
        options: TranscriptionOptions,
    ) -> None:
        self._update(
            job_id,
            status="running",
            progress=1,
            stage="starting",
            message="开始整曲双吉他处理",
            error=None,
        )

        def progress(value: int, stage: str, message: str) -> None:
            self._update(
                job_id,
                progress=max(0, min(100, value)),
                stage=stage,
                message=message,
            )

        try:
            outcome = SongTranscriber().transcribe(
                audio_path,
                output_dir,
                filename,
                options,
                progress,
            )
            self._update(
                job_id,
                status=outcome.status,
                progress=100,
                stage="completed",
                message=(
                    "双吉他扒谱完成"
                    if outcome.status == "succeeded"
                    else "扒谱完成，但有一把吉他需要重试"
                ),
                result=outcome.result,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="failed",
                message="整曲双吉他处理失败",
                error=str(exc),
            )

    def _update(self, job_id: str, **changes: Any) -> SongTranscriptionJob:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                raise UnknownJobError(job_id)
            payload = current.model_dump(mode="python")
            payload.update(
                {
                    **changes,
                    "updated_at": _utc_now(),
                    "revision": current.revision + 1,
                }
            )
            updated = SongTranscriptionJob.model_validate(payload)
            self._jobs[job_id] = updated
            return updated

    def get(self, job_id: str) -> SongTranscriptionJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise UnknownJobError(job_id)
            return job.model_copy(deep=True)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

