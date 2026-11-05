from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import main, online_search


def _netease_result(
    song_id: int,
    title: str,
    *,
    artist: str = "Guitar Backing Tracks",
    album: str = "国内伴奏合集",
    playable: bool = True,
) -> dict[str, object]:
    return {
        "id": song_id,
        "name": title,
        "ar": [{"name": artist}],
        "al": {
            "name": album,
            "picUrl": (
                "http://p1.music.126.net/"
                f"cover-{song_id}.jpg"
            ),
        },
        "privilege": {"pl": 320000 if playable else 0},
    }


def test_market_search_filters_and_ranks_backing_tracks(monkeypatch) -> None:
    async def fake_fetch(query: str, limit: int):
        if "无吉他" in query:
            return [
                _netease_result(
                    2,
                    "Hotel California (无人声伴奏)",
                    album="Guitar Backing Tracks",
                ),
                _netease_result(
                    1,
                    "Hotel California",
                    artist="Eagles",
                    album="Hotel California",
                ),
            ]
        return [
            _netease_result(3, "Hotel California (伴奏)"),
            _netease_result(2, "Hotel California (无人声伴奏)"),
        ]

    monkeypatch.setattr(online_search, "_fetch_netease", fake_fetch)
    result = asyncio.run(
        online_search.search_market(
            "Hotel California",
            "Eagles",
            ["guitar"],
        )
    )

    suggestions = result["suggestions"]
    assert result["provider"] == "网易云音乐 · 国内搜索"
    assert suggestions
    assert suggestions[0]["id"] == "2"
    assert suggestions[0]["kind"] == "无人声"
    assert all(item["id"] != "1" for item in suggestions)
    assert len({item["id"] for item in suggestions}) == len(suggestions)


def test_market_search_only_exposes_playable_preview(monkeypatch) -> None:
    async def fake_fetch(_query: str, _limit: int):
        return [
            _netease_result(
                10,
                "Test Song (伴奏)",
                playable=True,
            ),
            _netease_result(
                11,
                "Test Song (伴奏 VIP)",
                playable=False,
            ),
        ]

    monkeypatch.setattr(online_search, "_fetch_netease", fake_fetch)
    result = asyncio.run(
        online_search.search_market("Test Song", "", [])
    )
    by_id = {item["id"]: item for item in result["suggestions"]}

    assert by_id["10"]["preview_url"] is not None
    assert by_id["11"]["preview_url"] is None
    assert by_id["10"]["url"].startswith("https://music.163.com/")


def test_market_search_api(monkeypatch) -> None:
    async def fake_search(title, artist, remove_stems, limit):
        return {
            "provider": "网易云音乐 · 国内搜索",
            "queries": [f"{title} 伴奏"],
            "suggestions": [
                {
                    "id": "42",
                    "title": "Test Song (伴奏)",
                    "artist": "Test",
                    "album": "国内伴奏合集",
                    "kind": "伴奏",
                    "url": "https://music.163.com/#/song?id=42",
                    "preview_url": (
                        "https://music.163.com/song/media/outer/url?id=42.mp3"
                    ),
                    "artwork_url": None,
                    "relevance": 12,
                }
            ],
        }

    monkeypatch.setattr(main, "search_market", fake_search)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/market/search",
            json={
                "title": "Test Song",
                "artist": "",
                "remove_stems": ["guitar"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "网易云音乐 · 国内搜索"
    assert payload["suggestions"][0]["kind"] == "伴奏"
