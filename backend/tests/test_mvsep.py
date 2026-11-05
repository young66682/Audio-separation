from __future__ import annotations

import re
from pathlib import Path

import httpx

from app import mvsep
from app.mvsep import MvsepProvider


def test_mvsep_downloads_lead_and_rhythm_stems(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(mvsep, "MVSEP_POLL_INTERVAL_SECONDS", 0)
    calls = {"get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/separation/create"):
            assert b'name="sep_type"' in request.content
            assert b"101" in request.content
            assert re.search(
                rb'name="add_opt1"\r\n\r\n0\r\n',
                request.content,
            )
            return httpx.Response(
                200,
                json={"success": True, "data": {"hash": "job-123"}},
            )
        if request.url.path.endswith("/separation/get"):
            calls["get"] += 1
            if calls["get"] == 1:
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "status": "processing",
                        "data": {"progress": 42},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "status": "done",
                    "data": {
                        "files": [
                            {
                                "type": "lead-guitar",
                                "url": "https://files.test/lead.flac",
                            },
                            {
                                "type": "rhythm-guitar",
                                "url": "https://files.test/rhythm.flac",
                            },
                            {
                                "type": "no-guitar",
                                "url": "https://files.test/backing.flac",
                            },
                        ]
                    },
                },
            )
        if request.url.host == "files.test":
            return httpx.Response(200, content=request.url.path.encode())
        return httpx.Response(404)

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake audio")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(
        api_token="test-token",
        client=client,
        workflow="direct",
    )
    progress: list[int] = []
    result = provider.separate(
        audio,
        tmp_path / "stems",
        lambda value, _: progress.append(value),
    )

    assert result.lead.read_bytes() == b"/lead.flac"
    assert result.rhythm.read_bytes() == b"/rhythm.flac"
    assert result.backing is not None
    assert progress[-1] == 55


def test_mvsep_requires_a_token(tmp_path: Path) -> None:
    provider = MvsepProvider(api_token="", workflow="direct")
    try:
        provider.separate(tmp_path / "song.wav", tmp_path / "stems")
    except mvsep.MvsepError as exc:
        assert "MVSEP_API_TOKEN" in str(exc)
    else:
        raise AssertionError("missing token should fail")


def test_mvsep_reports_invalid_token_clearly(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"success": False})

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake audio")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(
        api_token="bad-token",
        client=client,
        workflow="direct",
    )

    try:
        provider.separate(audio, tmp_path / "stems")
    except mvsep.MvsepError as exc:
        assert "Token 无效或已过期" in str(exc)
    else:
        raise AssertionError("invalid token should fail")


def test_mvsep_guitar_first_workflow(tmp_path: Path) -> None:
    create_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/separation/create"):
            create_count["value"] += 1
            number = create_count["value"]
            return httpx.Response(
                200,
                json={"success": True, "data": {"hash": f"job-{number}"}},
            )
        if request.url.path.endswith("/separation/get"):
            job_hash = request.url.params.get("hash")
            if job_hash == "job-1":
                files = [
                    {
                        "type": "Guitar",
                        "url": "https://files.test/all-guitar.flac",
                    },
                    {
                        "type": "Other",
                        "url": "https://files.test/backing.flac",
                    },
                ]
            else:
                files = [
                    {
                        "type": "Lead guitar",
                        "url": "https://files.test/lead.flac",
                    },
                    {
                        "type": "Rhythm guitar",
                        "url": "https://files.test/rhythm.flac",
                    },
                    {
                        "type": "All guitar",
                        "url": "https://files.test/split-all.flac",
                    },
                ]
            return httpx.Response(
                200,
                json={"success": True, "status": "done", "data": {"files": files}},
            )
        if request.url.host == "files.test":
            return httpx.Response(200, content=request.url.path.encode())
        return httpx.Response(404)

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake audio")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(
        api_token="test-token",
        client=client,
        workflow="guitar_first",
    )
    result = provider.separate(audio, tmp_path / "stems")

    assert create_count["value"] == 2
    assert result.lead.read_bytes() == b"/lead.flac"
    assert result.rhythm.read_bytes() == b"/rhythm.flac"
    assert result.backing is not None
    assert result.backing.read_bytes() == b"/backing.flac"
    assert (tmp_path / "stems" / "all-guitar.flac").exists()


def test_mvsep_download_retries_after_connection_drop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(mvsep, "MVSEP_DOWNLOAD_RETRIES", 2)
    monkeypatch.setattr(mvsep, "MVSEP_DOWNLOAD_RETRY_DELAY_SECONDS", 0)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError(
                "peer closed connection",
                request=request,
            )
        return httpx.Response(
            200,
            content=b"complete-audio",
            headers={"Content-Length": "14"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(api_token="test", client=client)
    destination = tmp_path / "lead.flac"

    provider._download("https://files.test/lead.flac", destination)

    assert calls["count"] == 2
    assert destination.read_bytes() == b"complete-audio"


def test_mvsep_download_resumes_partial_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(mvsep, "MVSEP_DOWNLOAD_RETRIES", 0)
    destination = tmp_path / "lead.flac"
    partial = tmp_path / "lead.flac.part"
    partial.write_bytes(b"abc")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=3-"
        return httpx.Response(
            206,
            content=b"def",
            headers={
                "Content-Length": "3",
                "Content-Range": "bytes 3-5/6",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(api_token="test", client=client)

    provider._download("https://files.test/lead.flac", destination)

    assert destination.read_bytes() == b"abcdef"
    assert not partial.exists()


def test_mvsep_guitar_first_reuses_completed_all_guitar(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "stems"
    output_dir.mkdir(parents=True)
    (output_dir / "all-guitar.flac").write_bytes(b"x" * 2048)
    create_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/separation/create"):
            create_count["value"] += 1
            return httpx.Response(
                200,
                json={"success": True, "data": {"hash": "split-job"}},
            )
        if request.url.path.endswith("/separation/get"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "status": "done",
                    "data": {
                        "files": [
                            {
                                "type": "Lead guitar",
                                "url": "https://files.test/lead.flac",
                            },
                            {
                                "type": "Rhythm guitar",
                                "url": "https://files.test/rhythm.flac",
                            },
                        ]
                    },
                },
            )
        if request.url.host == "files.test":
            return httpx.Response(200, content=request.url.path.encode())
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(
        api_token="test-token",
        client=client,
        workflow="guitar_first",
    )
    result = provider.separate(tmp_path / "song.wav", output_dir)

    assert create_count["value"] == 1
    assert result.lead.read_bytes() == b"/lead.flac"
    assert result.rhythm.read_bytes() == b"/rhythm.flac"


def test_mvsep_retries_transient_poll_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(mvsep, "MVSEP_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mvsep, "MVSEP_POLL_RETRIES", 2)
    poll_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/separation/create"):
            return httpx.Response(
                200,
                json={"success": True, "data": {"hash": "job-1"}},
            )
        if request.url.path.endswith("/separation/get"):
            poll_count["value"] += 1
            if poll_count["value"] == 1:
                raise httpx.RemoteProtocolError(
                    "temporary disconnect",
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "status": "done",
                    "data": {
                        "files": [
                            {
                                "type": "Lead guitar",
                                "url": "https://files.test/lead.flac",
                            },
                            {
                                "type": "Rhythm guitar",
                                "url": "https://files.test/rhythm.flac",
                            },
                        ]
                    },
                },
            )
        if request.url.host == "files.test":
            return httpx.Response(200, content=b"audio")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MvsepProvider(
        api_token="test-token",
        client=client,
        workflow="direct",
    )
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")

    result = provider.separate(audio, tmp_path / "stems")

    assert poll_count["value"] == 2
    assert result.lead.exists()
    assert result.rhythm.exists()

