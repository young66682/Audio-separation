"""FastAPI application for guitar audio transcription."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import mimetypes
import platform
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    ALLOWED_AUDIO_EXTENSIONS,
    FRONTEND_DIST_DIR,
    MAX_UPLOAD_BYTES,
    MVSEP_API_TOKEN,
    MVSEP_MODEL_TYPE,
    MVSEP_WORKFLOW,
    ensure_runtime_directories,
)
from .guitar import parse_tuning
from .jobs import JobRunner, SongJobRunner, UnknownJobError
from .schemas import (
    HealthResponse,
    SongTranscriptionJob,
    TranscriptionCreated,
    TranscriptionJob,
    TranscriptionOptions,
)

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")


runner = JobRunner()
song_runner = SongJobRunner()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_directories()
    yield
    runner.shutdown()
    song_runner.shutdown()


app = FastAPI(
    title="吉他扒谱 API",
    version="0.1.0",
    description="将吉他音频转换为六线谱、MIDI 和 MusicXML。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "guitar.wav").name.strip()
    return name or "guitar.wav"


def _get_job(job_id: str) -> TranscriptionJob:
    try:
        return runner.get(job_id)
    except UnknownJobError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


def _get_song_job(job_id: str) -> SongTranscriptionJob:
    try:
        return song_runner.get(job_id)
    except UnknownJobError as exc:
        raise HTTPException(status_code=404, detail="整曲任务不存在") from exc


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        python=platform.python_version(),
        transcription_ready=importlib.util.find_spec("basic_pitch") is not None,
        cloud_separation_ready=bool(MVSEP_API_TOKEN),
        cloud_separation_model=(
            "MVSEP Guitar Isolation → Lead/Rhythm"
            if MVSEP_WORKFLOW == "guitar_first"
            else "MVSep Lead/Rhythm Guitar "
            f"({'one-stage' if MVSEP_MODEL_TYPE == '1' else 'two-stage'})"
        ),
        supported_formats=sorted(ALLOWED_AUDIO_EXTENSIONS),
        max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    )


@app.post(
    "/api/transcriptions",
    response_model=TranscriptionCreated,
    status_code=202,
)
async def create_transcription(
    audio: UploadFile = File(...),
    bpm: float = Form(0),
    tuning: str = Form("E2,A2,D3,G3,B3,E4"),
    capo: int = Form(0),
    max_fret: int = Form(17),
    max_fret_span: int = Form(5),
    min_duration_seconds: float = Form(0.08),
    min_velocity: float = Form(0.4),
) -> TranscriptionCreated:
    filename = _safe_filename(audio.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式: {extension or '未知'}",
        )
    try:
        options = TranscriptionOptions(
            bpm=bpm,
            tuning=tuning,
            capo=capo,
            max_fret=max_fret,
            max_fret_span=max_fret_span,
            min_duration_seconds=min_duration_seconds,
            min_velocity=min_velocity,
        )
        parse_tuning(options.tuning)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = runner.new_job(filename=filename, options=options)
    job_dir = runner.job_dir(job.id)
    input_path = job_dir / f"input{extension}"
    size = 0

    try:
        with input_path.open("wb") as destination:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 限制",
                    )
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
    except HTTPException as exc:
        runner.fail_upload(job.id, str(exc.detail))
        raise
    except Exception as exc:
        runner.fail_upload(job.id, f"保存上传文件失败: {exc}")
        raise HTTPException(status_code=500, detail="保存上传文件失败") from exc
    finally:
        await audio.close()

    runner.start(job.id, input_path)
    return TranscriptionCreated(job_id=job.id, status="queued")


@app.get("/api/transcriptions/{job_id}", response_model=TranscriptionJob)
def get_transcription(job_id: str) -> TranscriptionJob:
    return _get_job(job_id)


@app.get("/api/transcriptions/{job_id}/audio")
def get_audio(job_id: str) -> FileResponse:
    job = _get_job(job_id)
    job_dir = runner.job_dir(job.id)
    audio_files = [
        path
        for path in job_dir.glob("input.*")
        if path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
    ]
    if not audio_files:
        raise HTTPException(status_code=404, detail="原始音频不存在")
    media_type = mimetypes.guess_type(audio_files[0].name)[0] or "application/octet-stream"
    return FileResponse(audio_files[0], media_type=media_type, filename=job.filename)


@app.get("/api/transcriptions/{job_id}/artifacts/{artifact_key}")
def download_artifact(job_id: str, artifact_key: str) -> FileResponse:
    job = _get_job(job_id)
    filename = runner.artifact_filename(artifact_key)
    if filename is None:
        raise HTTPException(status_code=404, detail="未知导出格式")
    path = runner.job_dir(job.id) / filename
    if not path.exists() or job.result is None:
        raise HTTPException(status_code=404, detail="该导出文件尚未生成")
    return FileResponse(path, filename=filename)


@app.get("/api/transcriptions/{job_id}/events")
async def transcription_events(job_id: str) -> StreamingResponse:
    _get_job(job_id)

    async def event_stream():
        last_revision = -1
        while True:
            try:
                job = runner.get(job_id)
            except UnknownJobError:
                yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
                return
            if job.revision != last_revision:
                payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False)
                yield f"event: progress\ndata: {payload}\n\n"
                last_revision = job.revision
            if job.status in {"succeeded", "failed"}:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/api/song-transcriptions",
    response_model=TranscriptionCreated,
    status_code=202,
)
async def create_song_transcription(
    audio: UploadFile = File(...),
    bpm: float = Form(0),
    tuning: str = Form("E2,A2,D3,G3,B3,E4"),
    capo: int = Form(0),
    max_fret: int = Form(17),
    max_fret_span: int = Form(5),
    min_duration_seconds: float = Form(0.08),
    min_velocity: float = Form(0.4),
) -> TranscriptionCreated:
    if not bool(MVSEP_API_TOKEN):
        raise HTTPException(
            status_code=503,
            detail="整曲双吉他模式未配置 MVSEP_API_TOKEN，请先配置后端环境变量。",
        )

    filename = _safe_filename(audio.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式: {extension or '未知'}",
        )
    try:
        options = TranscriptionOptions(
            bpm=bpm,
            tuning=tuning,
            capo=capo,
            max_fret=max_fret,
            max_fret_span=max_fret_span,
            min_duration_seconds=min_duration_seconds,
            min_velocity=min_velocity,
        )
        parse_tuning(options.tuning)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = song_runner.new_job(filename=filename, options=options)
    job_dir = song_runner.job_dir(job.id)
    input_path = job_dir / f"input{extension}"
    size = 0
    try:
        with input_path.open("wb") as destination:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 限制",
                    )
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
    except HTTPException as exc:
        song_runner.fail_upload(job.id, str(exc.detail))
        raise
    except Exception as exc:
        song_runner.fail_upload(job.id, f"保存上传文件失败: {exc}")
        raise HTTPException(status_code=500, detail="保存上传文件失败") from exc
    finally:
        await audio.close()

    song_runner.start(job.id, input_path)
    return TranscriptionCreated(job_id=job.id, status="queued")


@app.get(
    "/api/song-transcriptions/{job_id}",
    response_model=SongTranscriptionJob,
)
def get_song_transcription(job_id: str) -> SongTranscriptionJob:
    return _get_song_job(job_id)


def _song_audio_path(job_id: str, stem_key: str) -> Path:
    job = _get_song_job(job_id)
    job_dir = song_runner.job_dir(job.id)
    if stem_key == "original":
        candidates = [
            path
            for path in job_dir.glob("input.*")
            if path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
        ]
    elif stem_key in {"lead", "rhythm", "backing"}:
        candidates = [
            path
            for path in (job_dir / "stems").glob(f"{stem_key}.*")
            if path.is_file()
        ]
    else:
        candidates = []
    if not candidates:
        raise HTTPException(status_code=404, detail="音频音轨不存在")
    return candidates[0]


@app.get("/api/song-transcriptions/{job_id}/audio/{stem_key}")
def get_song_audio(job_id: str, stem_key: str) -> FileResponse:
    path = _song_audio_path(job_id, stem_key)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get(
    "/api/song-transcriptions/{job_id}/guitars/{guitar_key}/artifacts/{artifact_key}"
)
def download_song_guitar_artifact(
    job_id: str,
    guitar_key: str,
    artifact_key: str,
) -> FileResponse:
    job = _get_song_job(job_id)
    if guitar_key not in {"lead", "rhythm"} or job.result is None:
        raise HTTPException(status_code=404, detail="吉他声部不存在")
    guitar = next(
        (item for item in job.result.guitars if item.key == guitar_key),
        None,
    )
    if guitar is None or guitar.transcription is None:
        raise HTTPException(status_code=404, detail="该吉他声部尚未生成结果")
    filename = runner.artifact_filename(artifact_key)
    if filename is None:
        raise HTTPException(status_code=404, detail="未知导出格式")
    path = song_runner.job_dir(job.id) / "guitars" / guitar_key / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="导出文件尚未生成")
    return FileResponse(path, filename=filename)


@app.get("/api/song-transcriptions/{job_id}/archive")
def download_song_archive(job_id: str) -> FileResponse:
    job = _get_song_job(job_id)
    if job.result is None:
        raise HTTPException(status_code=404, detail="整曲任务尚未完成")
    archives = list(song_runner.job_dir(job.id).glob("*-guitar-tabs.zip"))
    if not archives:
        raise HTTPException(status_code=404, detail="项目压缩包尚未生成")
    return FileResponse(archives[0], filename=archives[0].name)


@app.get("/api/song-transcriptions/{job_id}/score")
def download_song_score(job_id: str) -> FileResponse:
    job = _get_song_job(job_id)
    if job.result is None or not job.result.score_artifact:
        raise HTTPException(status_code=404, detail="合并乐谱尚未生成")
    path = song_runner.job_dir(job.id) / job.result.score_artifact
    if not path.exists():
        raise HTTPException(status_code=404, detail="合并乐谱文件不存在")
    return FileResponse(path, media_type="application/vnd.recordare.musicxml+xml")


@app.get("/api/song-transcriptions/{job_id}/events")
async def song_transcription_events(job_id: str) -> StreamingResponse:
    _get_song_job(job_id)

    async def event_stream():
        last_revision = -1
        while True:
            try:
                job = song_runner.get(job_id)
            except UnknownJobError:
                yield "event: error\ndata: {\"detail\":\"整曲任务不存在\"}\n\n"
                return
            if job.revision != last_revision:
                payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False)
                yield f"event: progress\ndata: {payload}\n\n"
                last_revision = job.revision
            if job.status in {"succeeded", "partial", "failed"}:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.exception_handler(UnknownJobError)
async def unknown_job_handler(_, __) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "任务不存在"})


if FRONTEND_DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        requested = FRONTEND_DIST_DIR / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")

