"""API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed"]
SongJobStatus = Literal["queued", "running", "succeeded", "partial", "failed"]


class TranscriptionOptions(BaseModel):
    bpm: float = Field(default=0, ge=0, le=400)
    tuning: str = "E2,A2,D3,G3,B3,E4"
    capo: int = Field(default=0, ge=0, le=12)
    max_fret: int = Field(default=17, ge=5, le=24)
    max_fret_span: int = Field(default=5, ge=2, le=12)
    min_duration_seconds: float = Field(default=0.08, ge=0.03, le=1)
    min_velocity: float = Field(default=0.4, ge=0, le=1)


class TranscriptionJob(BaseModel):
    id: str
    filename: str
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = "等待处理"
    message: str = ""
    created_at: datetime
    updated_at: datetime
    options: TranscriptionOptions
    result: dict[str, Any] | None = None
    error: str | None = None
    revision: int = 0


class TranscriptionCreated(BaseModel):
    job_id: str
    status: JobStatus


class HealthResponse(BaseModel):
    status: str
    python: str
    transcription_ready: bool
    cloud_separation_ready: bool
    cloud_separation_model: str
    supported_formats: list[str]
    max_upload_mb: int


class GuitarPartResult(BaseModel):
    key: Literal["lead", "rhythm"]
    label: str
    audio_format: str
    transcription: dict[str, Any] | None = None
    error: str | None = None


class SongTranscriptionResult(BaseModel):
    title: str
    bpm: float
    source: str = "mvsep-lead-rhythm"
    guitars: list[GuitarPartResult]
    backing_available: bool = False
    warnings: list[str] = Field(default_factory=list)
    score_artifact: str | None = None


class SongTranscriptionJob(BaseModel):
    id: str
    filename: str
    status: SongJobStatus
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = "等待处理"
    message: str = ""
    created_at: datetime
    updated_at: datetime
    options: TranscriptionOptions
    result: SongTranscriptionResult | None = None
    error: str | None = None
    revision: int = 0

