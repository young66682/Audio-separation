"""Client for MVSEP's Lead/Rhythm Guitar separation model."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

from .config import (
    MVSEP_API_TOKEN,
    MVSEP_API_URL,
    MVSEP_DOWNLOAD_RETRIES,
    MVSEP_DOWNLOAD_RETRY_DELAY_SECONDS,
    MVSEP_JOB_TIMEOUT_SECONDS,
    MVSEP_MODEL_TYPE,
    MVSEP_OUTPUT_FORMAT,
    MVSEP_POLL_INTERVAL_SECONDS,
    MVSEP_POLL_RETRIES,
    MVSEP_SEPARATION_TYPE,
    MVSEP_USE_ENV_PROXY,
    MVSEP_WORKFLOW,
)


ProgressCallback = Callable[[int, str], None]


class MvsepError(RuntimeError):
    """Raised when MVSEP rejects or cannot complete a separation."""


@dataclass(frozen=True)
class SeparationResult:
    lead: Path
    rhythm: Path
    backing: Path | None


def _stem_key(*values: Any) -> str | None:
    haystack = " ".join(str(value or "") for value in values).lower()
    haystack = re.sub(r"[_\s]+", "-", haystack)
    if "no-guitar" in haystack or "backing" in haystack or "instrumental" in haystack:
        return "backing"
    if "rhythm" in haystack:
        return "rhythm"
    if "lead" in haystack:
        return "lead"
    return None


def _stage_one_key(*values: Any) -> str | None:
    haystack = " ".join(str(value or "") for value in values).lower()
    haystack = re.sub(r"[_\s]+", "-", haystack)
    if "no-guitar" in haystack or "other" in haystack:
        return "backing"
    if "guitar" in haystack:
        return "all-guitar"
    return None


class MvsepProvider:
    """Use MVSEP's ready-made two-stage lead/rhythm guitar model."""

    def __init__(
        self,
        api_token: str | None = None,
        client: httpx.Client | None = None,
        model_type: str | None = None,
        workflow: str | None = None,
    ) -> None:
        self.api_token = (api_token if api_token is not None else MVSEP_API_TOKEN).strip()
        self.model_type = model_type if model_type is not None else MVSEP_MODEL_TYPE
        self.workflow = workflow or MVSEP_WORKFLOW
        self._owns_client = client is None
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(120.0, connect=30.0),
            headers={"User-Agent": "Fretline/0.1"},
            trust_env=MVSEP_USE_ENV_PROXY,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_token)

    @property
    def model_name(self) -> str:
        model_label = "one-stage" if self.model_type == "1" else "two-stage"
        if self.workflow == "guitar_first":
            return f"MVSEP Guitar Isolation → Lead/Rhythm ({model_label})"
        return f"MVSep Lead/Rhythm Guitar ({model_label})"

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def separate(
        self,
        audio_path: Path,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> SeparationResult:
        if not self.configured:
            raise MvsepError(
                "未配置 MVSEP_API_TOKEN。请在 backend/.env 中填写 Token 后重启后端。"
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        if self.workflow == "guitar_first":
            return self._separate_guitar_first(
                audio_path,
                output_dir,
                progress_callback,
            )

        progress_callback and progress_callback(2, "正在上传整曲到 MVSEP")
        job_hash = self._create_job(
            audio_path,
            MVSEP_SEPARATION_TYPE,
            self.model_type,
        )
        progress_callback and progress_callback(5, "MVSEP 已接收歌曲，等待分离")
        files = self._wait_for_result(job_hash, progress_callback)

        downloaded: dict[str, Path] = {}
        for file_info in files:
            url = file_info.get("url")
            if not url:
                continue
            key = _stem_key(
                file_info.get("type"),
                file_info.get("name"),
                urlparse(str(url)).path.rsplit("/", 1)[-1],
            )
            if key is None or key in downloaded:
                continue
            extension = Path(urlparse(str(url)).path).suffix.lower() or ".flac"
            destination = output_dir / f"{key}{extension}"
            progress_callback and progress_callback(48, f"正在下载 {key} 吉他音轨")
            self._download(urljoin(f"{MVSEP_API_URL}/", str(url)), destination)
            downloaded[key] = destination

        missing = [key for key in ("lead", "rhythm") if key not in downloaded]
        if missing:
            raise MvsepError(
                "MVSEP 未返回完整的主音/节奏吉他结果："
                + ", ".join(missing)
            )
        progress_callback and progress_callback(55, "双吉他分离完成")
        return SeparationResult(
            lead=downloaded["lead"],
            rhythm=downloaded["rhythm"],
            backing=downloaded.get("backing"),
        )

    def _separate_guitar_first(
        self,
        audio_path: Path,
        output_dir: Path,
        progress_callback: ProgressCallback | None,
    ) -> SeparationResult:
        all_guitar = self._find_cached_stem(output_dir, "all-guitar")
        backing = self._find_cached_stem(output_dir, "backing")
        if all_guitar is not None:
            progress_callback and progress_callback(
                28, "复用已下载的全部吉他音轨，继续后续处理"
            )
        else:
            progress_callback and progress_callback(
                2, "正在上传整曲，提取全部吉他"
            )
            guitar_job = self._create_job(audio_path, "31", "7")
            progress_callback and progress_callback(5, "全部吉他音轨排队中")
            guitar_files = self._wait_for_result(
                guitar_job,
                progress_callback,
                base_progress=8,
                stage_label="全部吉他",
            )

            for file_info in guitar_files:
                key = _stage_one_key(
                    file_info.get("type"),
                    file_info.get("name"),
                    file_info.get("url"),
                )
                if key == "all-guitar" and all_guitar is None:
                    all_guitar = self._download_file(
                        file_info,
                        output_dir,
                        "all-guitar",
                        progress_callback,
                        24,
                    )
                elif key == "backing" and backing is None:
                    backing = self._download_file(
                        file_info,
                        output_dir,
                        "backing",
                        progress_callback,
                        28,
                    )
            if all_guitar is None:
                raise MvsepError("MVSEP 未能提取出全部吉他音轨")

        cached_lead = self._find_cached_stem(output_dir, "lead")
        cached_rhythm = self._find_cached_stem(output_dir, "rhythm")
        if cached_lead is not None and cached_rhythm is not None:
            progress_callback and progress_callback(
                55, "复用已完成的主音与节奏吉他音轨"
            )
            return SeparationResult(
                lead=cached_lead,
                rhythm=cached_rhythm,
                backing=backing,
            )

        progress_callback and progress_callback(
            30, "正在拆分主音吉他与节奏吉他"
        )
        split_job = self._create_job(
            all_guitar,
            MVSEP_SEPARATION_TYPE,
            self.model_type,
        )
        progress_callback and progress_callback(33, "主音/节奏吉他分离排队中")
        split_files = self._wait_for_result(
            split_job,
            progress_callback,
            base_progress=35,
            stage_label="主音/节奏吉他",
        )
        downloaded: dict[str, Path] = {}
        for file_info in split_files:
            key = _stem_key(
                file_info.get("type"),
                file_info.get("name"),
                file_info.get("url"),
            )
            if key not in {"lead", "rhythm"} or key in downloaded:
                continue
            downloaded[key] = self._download_file(
                file_info,
                output_dir,
                key,
                progress_callback,
                48,
            )

        missing = [key for key in ("lead", "rhythm") if key not in downloaded]
        if missing:
            raise MvsepError(
                "MVSEP 未返回完整的主音/节奏吉他结果：" + ", ".join(missing)
            )
        progress_callback and progress_callback(55, "双吉他分离完成")
        return SeparationResult(
            lead=downloaded["lead"],
            rhythm=downloaded["rhythm"],
            backing=backing,
        )

    @staticmethod
    def _find_cached_stem(output_dir: Path, key: str) -> Path | None:
        """查找上一次任务已完整落盘的音轨。"""
        for path in output_dir.glob(f"{key}.*"):
            if (
                path.is_file()
                and path.suffix.lower() in {".flac", ".wav", ".mp3", ".ogg"}
                and path.stat().st_size > 1024
            ):
                return path
        return None

    def _download_file(
        self,
        file_info: dict[str, Any],
        output_dir: Path,
        key: str,
        progress_callback: ProgressCallback | None,
        progress_value: int,
    ) -> Path:
        url = file_info.get("url")
        if not url:
            raise MvsepError(f"MVSEP 返回的 {key} 音轨缺少下载地址")
        extension = Path(urlparse(str(url)).path).suffix.lower() or ".flac"
        destination = output_dir / f"{key}{extension}"
        progress_callback and progress_callback(
            progress_value,
            f"正在下载 {key} 音轨",
        )
        self._download(urljoin(f"{MVSEP_API_URL}/", str(url)), destination)
        return destination

    def _create_job(
        self,
        audio_path: Path,
        separation_type: str,
        model_type: str,
    ) -> str:
        try:
            with audio_path.open("rb") as audio_file:
                response = self.client.post(
                    f"{MVSEP_API_URL}/separation/create",
                    data={
                        "api_token": self.api_token,
                        "sep_type": separation_type,
                        "add_opt1": model_type,
                        "output_format": MVSEP_OUTPUT_FORMAT,
                    },
                    files={
                        "audiofile": (
                            audio_path.name,
                            audio_file,
                            "application/octet-stream",
                        )
                    },
                    timeout=httpx.Timeout(300.0, connect=30.0),
                )
            if response.status_code == 401:
                raise MvsepError(
                    "MVSEP API Token 无效或已过期。请登录 MVSEP，"
                    "在 API 页面重新获取 Token，并更新 backend/.env 后重启后端。"
                )
            if response.status_code == 403:
                raise MvsepError(
                    "MVSEP 拒绝了该请求，请检查账号权限、免费额度和文件限制。"
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MvsepError(f"MVSEP 上传请求失败：{exc}") from exc

        if not body.get("success"):
            message = (body.get("data") or {}).get("message") or body.get("message")
            raise MvsepError(f"MVSEP 拒绝了分离任务：{message or '未知错误'}")
        job_hash = (body.get("data") or {}).get("hash")
        if not job_hash:
            raise MvsepError("MVSEP 返回结果缺少任务 hash")
        return str(job_hash)

    def _wait_for_result(
        self,
        job_hash: str,
        progress_callback: ProgressCallback | None,
        base_progress: int = 8,
        stage_label: str = "",
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + MVSEP_JOB_TIMEOUT_SECONDS
        consecutive_errors = 0
        while time.monotonic() < deadline:
            try:
                response = self.client.get(
                    f"{MVSEP_API_URL}/separation/get",
                    params={"hash": job_hash},
                    timeout=httpx.Timeout(60.0, connect=20.0),
                )
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                consecutive_errors += 1
                if consecutive_errors > MVSEP_POLL_RETRIES:
                    raise MvsepError(
                        f"查询 MVSEP 任务失败：{exc}"
                    ) from exc
                progress_callback and progress_callback(
                    base_progress,
                    f"MVSEP 查询暂时中断，正在重试"
                    f"（{consecutive_errors}/{MVSEP_POLL_RETRIES}）",
                )
                time.sleep(MVSEP_POLL_INTERVAL_SECONDS)
                continue
            consecutive_errors = 0

            data = body.get("data") or {}
            status = str(body.get("status") or "").lower()
            if status == "done":
                files = data.get("files") or body.get("files") or []
                if not isinstance(files, list):
                    raise MvsepError("MVSEP 返回的文件列表格式不正确")
                return files
            if status == "failed" or body.get("success") is False:
                message = data.get("message") or body.get("message") or "未知错误"
                raise MvsepError(f"MVSEP 分离失败：{message}")

            if status == "waiting":
                position = data.get("current_order")
                prefix = f"{stage_label}：" if stage_label else ""
                message = (
                    f"{prefix}MVSEP 排队中，当前第 {position} 位"
                    if position
                    else f"{prefix}MVSEP 排队中"
                )
            elif status == "processing":
                remote_progress = data.get("progress")
                prefix = f"{stage_label}：" if stage_label else ""
                message = f"{prefix}MVSEP 正在处理"
                if remote_progress is not None:
                    message += f"（{remote_progress}%）"
            else:
                message = "等待 MVSEP 分离结果"
            progress_callback and progress_callback(base_progress, message)
            time.sleep(MVSEP_POLL_INTERVAL_SECONDS)

        raise MvsepError(
            f"等待 MVSEP 超时（{MVSEP_JOB_TIMEOUT_SECONDS // 60} 分钟）"
        )

    def _download(self, url: str, destination: Path) -> None:
        """带断点续传和完整性校验下载 MVSEP 音轨。"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f"{destination.name}.part")
        last_error: Exception | None = None

        for attempt in range(MVSEP_DOWNLOAD_RETRIES + 1):
            existing_bytes = partial.stat().st_size if partial.exists() else 0
            headers = {"Accept-Encoding": "identity"}
            if existing_bytes:
                headers["Range"] = f"bytes={existing_bytes}-"

            try:
                with self.client.stream(
                    "GET",
                    url,
                    headers=headers,
                    timeout=httpx.Timeout(
                        600.0,
                        connect=30.0,
                        read=60.0,
                        write=30.0,
                        pool=30.0,
                    ),
                ) as response:
                    if response.status_code == 416 and existing_bytes:
                        os.replace(partial, destination)
                        return
                    response.raise_for_status()

                    resumed = response.status_code == 206 and existing_bytes > 0
                    mode = "ab" if resumed else "wb"
                    start_bytes = existing_bytes if resumed else 0
                    content_range = response.headers.get("content-range", "")
                    total_match = re.search(r"/(\d+)$", content_range)
                    expected_total = (
                        int(total_match.group(1))
                        if total_match
                        else (
                            start_bytes + int(response.headers["content-length"])
                            if response.headers.get("content-length")
                            else None
                        )
                    )
                    expected_chunk = (
                        int(response.headers["content-length"])
                        if response.headers.get("content-length")
                        else None
                    )
                    written = 0
                    with partial.open(mode) as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            output.write(chunk)
                            written += len(chunk)

                    actual_size = partial.stat().st_size
                    if expected_chunk is not None and written != expected_chunk:
                        raise MvsepError(
                            f"下载不完整：收到 {written} 字节，"
                            f"应为 {expected_chunk} 字节"
                        )
                    if expected_total is not None and actual_size != expected_total:
                        raise MvsepError(
                            f"文件长度不匹配：实际 {actual_size} 字节，"
                            f"应为 {expected_total} 字节"
                        )
                    if actual_size == 0:
                        raise MvsepError("下载得到的音轨文件为空")
                    os.replace(partial, destination)
                    return
            except (httpx.HTTPError, OSError, MvsepError) as exc:
                last_error = exc
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and 400 <= exc.response.status_code < 500
                    and exc.response.status_code not in {408, 429}
                ):
                    break
                if attempt < MVSEP_DOWNLOAD_RETRIES:
                    time.sleep(
                        MVSEP_DOWNLOAD_RETRY_DELAY_SECONDS * (2 ** attempt)
                    )

        cached_bytes = partial.stat().st_size if partial.exists() else 0
        raise MvsepError(
            f"下载 MVSEP 音轨失败，已尝试 {MVSEP_DOWNLOAD_RETRIES + 1} 次"
            f"（保留断点 {cached_bytes} 字节）：{last_error}"
        ) from last_error
