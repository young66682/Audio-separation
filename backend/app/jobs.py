"""基于线程池的本地扒谱与分离任务管理。"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import JOBS_DIR, SEPARATION_JOBS_DIR, SONG_JOBS_DIR
from .local_separation import LocalSeparator
from .schemas import (
    SeparationJob,
    SeparationOptions,
    SongTranscriptionJob,
    TranscriptionJob,
    TranscriptionOptions,
)
from .song_transcriber import SongTranscriber
from .transcriber import GuitarTranscriber


class UnknownJobError(KeyError):
    """当前进程中不存在指定任务时抛出。"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _persist_job_snapshot(directory: Path, job: Any) -> None:
    """原子写入任务快照，避免进程中断留下半个 JSON。"""
    target = directory / "job.json"
    temporary = directory / "job.json.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            job.model_dump_json(indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        print(f"[jobs] 任务快照写入失败：{exc}", flush=True)


def _load_job_snapshots(
    directory: Path,
    job_type: type[Any],
    *,
    excluded_directories: set[str] | None = None,
) -> dict[str, Any]:
    """加载历史任务；上次运行中的任务标记为中断。"""
    if not directory.exists():
        return {}
    excluded = excluded_directories or set()
    jobs: dict[str, Any] = {}
    for snapshot in directory.glob("*/job.json"):
        if snapshot.parent.name in excluded:
            continue
        try:
            job = job_type.model_validate_json(
                snapshot.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        if job.status in {"queued", "running"}:
            payload = job.model_dump(mode="python")
            payload.update(
                {
                    "status": "failed",
                    "stage": "interrupted",
                    "message": "服务重启，任务已中断",
                    "error": "服务重启导致任务中断，可以重新提交或重试。",
                    "updated_at": _utc_now(),
                    "revision": job.revision + 1,
                }
            )
            job = job_type.model_validate(payload)
            _persist_job_snapshot(snapshot.parent, job)
        jobs[job.id] = job
    return jobs


class JobRunner:
    """串行执行单吉他扒谱，并提供可供查询的进度快照。"""

    def __init__(self) -> None:
        self._jobs: dict[str, TranscriptionJob] = _load_job_snapshots(
            JOBS_DIR,
            TranscriptionJob,
            excluded_directories={"songs", "separations"},
        )
        self._lock = threading.RLock()
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
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
            _persist_job_snapshot(JOBS_DIR / job.id, job)
        return job

    def job_dir(self, job_id: str) -> Path:
        job = self.get(job_id)
        directory = JOBS_DIR / job.id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def start(self, job_id: str, audio_path: Path) -> None:
        job = self.get(job_id)
        output_dir = self.job_dir(job_id)
        self._ensure_executor().submit(
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
            _persist_job_snapshot(JOBS_DIR / job_id, updated)
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

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="guitar-transcriber",
                )
            return self._executor

    def shutdown(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


class SongJobRunner:
    """串行执行整曲双吉他分离与扒谱任务。"""

    def __init__(self) -> None:
        self._jobs: dict[str, SongTranscriptionJob] = _load_job_snapshots(
            SONG_JOBS_DIR,
            SongTranscriptionJob,
        )
        self._lock = threading.RLock()
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
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
            _persist_job_snapshot(SONG_JOBS_DIR / job.id, job)
        return job

    def job_dir(self, job_id: str) -> Path:
        job = self.get(job_id)
        directory = SONG_JOBS_DIR / job.id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def start(self, job_id: str, audio_path: Path) -> None:
        job = self.get(job_id)
        self._ensure_executor().submit(
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

    def retry(self, job_id: str) -> SongTranscriptionJob:
        """重试失败的双吉他任务，并复用已下载完成的音轨。"""
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                raise UnknownJobError(job_id)
            if current.status not in {"failed", "partial"}:
                raise ValueError("只有失败或部分完成的任务可以重试")
            input_files = [
                path
                for path in self.job_dir(job_id).glob("input.*")
                if path.is_file()
            ]
            if not input_files:
                raise FileNotFoundError("任务原始音频不存在，请重新上传")
            audio_path = input_files[0]
        self._update(
            job_id,
            status="queued",
            progress=0,
            stage="queued",
            message="正在从已有分轨恢复任务",
            error=None,
            result=None,
        )
        self.start(job_id, audio_path)
        return self.get(job_id)

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
            _persist_job_snapshot(SONG_JOBS_DIR / job_id, updated)
            return updated

    def get(self, job_id: str) -> SongTranscriptionJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise UnknownJobError(job_id)
            return job.model_copy(deep=True)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="song-guitar-transcriber",
                )
            return self._executor

    def shutdown(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


class SeparationJobRunner:
    """串行执行本地 Demucs 任务，避免并发占用过多内存。"""

    def __init__(self) -> None:
        self._jobs: dict[str, SeparationJob] = _load_job_snapshots(
            SEPARATION_JOBS_DIR,
            SeparationJob,
        )
        self._lock = threading.RLock()
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="local-separator",
        )

    def new_job(
        self,
        filename: str,
        options: SeparationOptions,
    ) -> SeparationJob:
        now = _utc_now()
        job = SeparationJob(
            id=uuid.uuid4().hex,
            filename=filename,
            status="queued",
            progress=0,
            stage="queued",
            message="分离任务已进入队列",
            created_at=now,
            updated_at=now,
            options=options,
        )
        with self._lock:
            self._jobs[job.id] = job
            _persist_job_snapshot(SEPARATION_JOBS_DIR / job.id, job)
        return job

    def job_dir(self, job_id: str) -> Path:
        job = self.get(job_id)
        directory = SEPARATION_JOBS_DIR / job.id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def start(self, job_id: str, audio_path: Path) -> None:
        job = self.get(job_id)
        self._ensure_executor().submit(
            self._run,
            job_id,
            audio_path,
            self.job_dir(job_id),
            job.options,
            job.filename,
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
        options: SeparationOptions,
        original_filename: str,
    ) -> None:
        self._update(
            job_id,
            status="running",
            progress=1,
            stage="starting",
            message="开始本地音轨分离",
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
            result = LocalSeparator().separate(
                audio_path,
                output_dir,
                options.model,
                options.remove_stems,
                options.quality,
                progress,
                original_filename,
            )
            self._update(
                job_id,
                status="succeeded",
                progress=100,
                stage="completed",
                message="分离与伴奏生成完成",
                result=result,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="failed",
                message="音轨分离失败",
                error=str(exc),
            )

    def _update(self, job_id: str, **changes: Any) -> SeparationJob:
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
            updated = SeparationJob.model_validate(payload)
            self._jobs[job_id] = updated
            _persist_job_snapshot(SEPARATION_JOBS_DIR / job_id, updated)
            return updated

    def get(self, job_id: str) -> SeparationJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise UnknownJobError(job_id)
            return job.model_copy(deep=True)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="local-separator",
                )
            return self._executor

    def shutdown(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

