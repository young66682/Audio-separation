"""API 请求与响应数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed"]
SongJobStatus = Literal["queued", "running", "succeeded", "partial", "failed"]
SeparationQuality = Literal["fast", "balanced", "best"]


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
    local_separation_ready: bool
    separation_device: str | None = None
    separation_models: list[dict[str, Any]] = Field(default_factory=list)
    supported_formats: list[str]
    max_upload_mb: int


class SeparationOptions(BaseModel):
    model: str = "htdemucs"
    remove_stems: list[str] = Field(default_factory=list)
    quality: SeparationQuality = "balanced"


class SeparationCreated(BaseModel):
    job_id: str
    status: JobStatus


class SeparationStemResult(BaseModel):
    key: str
    label: str
    filename: str
    audio_format: str


class AccompanimentResult(BaseModel):
    key: str
    label: str
    removed_stem: str
    removed_label: str
    filename: str
    audio_format: str


class SeparationResult(BaseModel):
    title: str
    model: dict[str, str]
    device: str
    quality: SeparationQuality
    duration_seconds: float | None = None
    stems: list[SeparationStemResult]
    accompaniments: list[AccompanimentResult]
    warnings: list[str] = Field(default_factory=list)
    archive_filename: str | None = None


class SeparationJob(BaseModel):
    id: str
    filename: str
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = "等待处理"
    message: str = ""
    created_at: datetime
    updated_at: datetime
    options: SeparationOptions
    result: SeparationResult | None = None
    error: str | None = None
    revision: int = 0


class MarketSearchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default="", max_length=200)
    remove_stems: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=12)


class MarketSuggestion(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    kind: str
    url: str
    preview_url: str | None = None
    artwork_url: str | None = None
    relevance: int = 0


class MarketSearchResponse(BaseModel):
    provider: str
    queries: list[str]
    suggestions: list[MarketSuggestion]


class RecentJobSummary(BaseModel):
    id: str
    mode: Literal["guitar", "song", "separate"]
    filename: str
    status: str
    progress: int
    message: str
    updated_at: datetime
    result_title: str | None = None


class RecentJobsResponse(BaseModel):
    jobs: list[RecentJobSummary]


class ScoreSearchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default="", max_length=200)
    limit: int = Field(default=8, ge=1, le=12)


class ScoreSuggestion(BaseModel):
    id: str
    title: str
    artist: str
    type: str
    version: str
    rating: float
    votes: int
    url: str
    provider: str
    meta: str = ""


class ScoreLibrary(BaseModel):
    name: str
    url: str


class ScoreSearchResponse(BaseModel):
    provider: str
    query: str
    suggestions: list[ScoreSuggestion]
    libraries: list[ScoreLibrary]


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

