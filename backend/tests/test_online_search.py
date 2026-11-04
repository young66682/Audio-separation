from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import main, online_search


def _apple_result(
    track_id: int,
    title: str,
    *,
    artist: str = "Backing Tracks For Guitarists",
    album: str = "Backing Tracks, Vol. 1",
) -> dict[str, object]:
    return {
        "trackId": track_id,
        "trackName": title,
        "artistName": artist,
        "collectionName": album,
        "trackViewUrl": f"https://music.apple.com/us/album/test/{track_id}",
        "previewUrl": (
            "https://audio-ssl.itunes.apple.com/itunes-assets/preview.m4a"
        ),
        "artworkUrl100": (
            "https://is1-ssl.mzstatic.com/image/thumb/artwork.jpg"
        ),
    }


def test_market_search_filters_and_ranks_backing_tracks(monkeypatch) -> None:
    async def fake_fetch(query: str, limit: int):
        if "minus guitar" in query:
            return [
                _apple_result(
                    2,
                    "Hotel California (Minus All Guitars)",
                    album="Guitar Backing Tracks",
                ),
                _apple_result(
                    1,
                    "Hotel California",
                    artist="Eagles",
                    album="Hotel California",
                ),
            ]
        return [
            _apple_result(3, "Hotel California (Backing Track)"),
            _apple_result(2, "Hotel California (Minus All Guitars)"),
        ]

    monkeypatch.setattr(online_search, "_fetch_itunes", fake_fetch)
    result = asyncio.run(
        online_search.search_market(
            "Hotel California",
            "Eagles",
            ["guitar"],
        )
    )

    suggestions = result["suggestions"]
    assert suggestions
    assert all(item["id"] == "2" or "backing" in item["title"].lower()
               for item in suggestions)
    assert suggestions[0]["id"] == "2"
    assert suggestions[0]["kind"] == "Minus One"
    assert len({item["id"] for item in suggestions}) == len(suggestions)


def test_market_search_api(monkeypatch) -> None:
    async def fake_search(title, artist, remove_stems, limit):
        return {
            "provider": "Apple Music / iTunes Search",
            "queries": [f"{title} backing track"],
            "suggestions": [
                {
                    "id": "42",
                    "title": "Test Song (Backing Track)",
                    "artist": "Test",
                    "album": "Backing Tracks",
                    "kind": "Backing Track",
                    "url": "https://music.apple.com/us/album/test/42",
                    "preview_url": None,
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
    assert payload["suggestions"][0]["kind"] == "Backing Track"
