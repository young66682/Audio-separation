from __future__ import annotations

import asyncio
import html
import json

from fastapi.testclient import TestClient

from app import main, score_search


def _score(
    tab_id: int,
    kind: str,
    *,
    rating: float,
    votes: int,
    url_host: str = "tabs.ultimate-guitar.com",
    song_name: str = "Test Song",
    artist_name: str = "Test Artist",
) -> dict[str, object]:
    return {
        "id": tab_id,
        "song_name": song_name,
        "artist_name": artist_name,
        "type": kind,
        "version": "1",
        "rating": rating,
        "votes": votes,
        "tab_url": f"https://{url_host}/tab/test-song-{tab_id}",
    }


def test_score_search_ranks_tabs_and_filters_other_hosts(monkeypatch) -> None:
    results = [
        _score(1, "Chords", rating=4.9, votes=5000),
        _score(2, "Tabs", rating=4.8, votes=900),
        _score(3, "Tabs", rating=4.9, votes=3000),
        _score(4, "Bass", rating=4.8, votes=100),
        _score(5, "Tabs", rating=5.0, votes=1000, url_host="example.com"),
    ]
    page_data = {"store": {"page": {"data": {"results": results}}}}
    page = (
        "<html><div data-content=\""
        + html.escape(json.dumps(page_data), quote=True)
        + '"></div></html>'
    )

    async def fake_fetch(_: str) -> str:
        return page

    async def empty_tan8(_: str, __: int):
        return []

    monkeypatch.setattr(score_search, "_fetch_tan8", empty_tan8)
    monkeypatch.setattr(
        score_search,
        "_fetch_ultimate_guitar",
        fake_fetch,
    )
    result = asyncio.run(
        score_search.search_scores("Test Song", "Test Artist")
    )

    suggestions = result["suggestions"]
    assert [item["id"] for item in suggestions[:2]] == ["3", "2"]
    assert all(
        item["url"].startswith("https://tabs.ultimate-guitar.com/")
        for item in suggestions
    )
    assert [item["name"] for item in result["libraries"]] == [
        "弹琴吧",
        "Ultimate Guitar",
        "Songsterr",
        "MuseScore",
    ]


def test_score_search_api(monkeypatch) -> None:
    async def fake_search(title: str, artist: str, limit: int):
        return {
            "provider": "Ultimate Guitar",
            "query": f"{title} {artist}".strip(),
            "suggestions": [
                {
                    "id": "42",
                    "title": title,
                    "artist": artist,
                    "type": "Tabs",
                    "version": "1",
                    "rating": 4.9,
                    "votes": 100,
                    "url": "https://tabs.ultimate-guitar.com/tab/test-42",
                    "provider": "Ultimate Guitar",
                }
            ],
            "libraries": [],
        }

    monkeypatch.setattr(main, "search_scores", fake_search)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/scores/search",
            json={
                "title": "Test Song",
                "artist": "Test Artist",
            },
        )

    assert response.status_code == 200
    assert response.json()["suggestions"][0]["type"] == "Tabs"


def test_exact_song_name_beats_unrelated_high_vote_tabs(monkeypatch) -> None:
    results = [
        _score(
            10,
            "Tabs",
            rating=5.0,
            votes=99_999,
            song_name="Unrelated Song",
        ),
        _score(
            11,
            "Chords",
            rating=4.1,
            votes=3,
            song_name="海阔天空",
            artist_name="Beyond",
        ),
        _score(
            12,
            "Tabs",
            rating=4.9,
            votes=500,
            song_name="海阔天空 (Live Version)",
            artist_name="Beyond",
        ),
    ]
    page_data = {"store": {"page": {"data": {"results": results}}}}
    page = (
        "<html><div data-content=\""
        + html.escape(json.dumps(page_data, ensure_ascii=False), quote=True)
        + '"></div></html>'
    )

    async def fake_fetch(_: str) -> str:
        return page

    async def empty_tan8(_: str, __: int):
        return []

    monkeypatch.setattr(score_search, "_fetch_tan8", empty_tan8)
    monkeypatch.setattr(
        score_search,
        "_fetch_ultimate_guitar",
        fake_fetch,
    )
    result = asyncio.run(
        score_search.search_scores("海阔天空", "Beyond")
    )

    assert [item["id"] for item in result["suggestions"][:2]] == [
        "11",
        "12",
    ]


def test_tan8_is_primary_for_simplified_chinese_search(monkeypatch) -> None:
    async def fake_tan8(title: str, limit: int):
        assert title == "海阔天空"
        assert limit == 8
        return [
            {
                "id": "tan8-exact",
                "title": "海阔天空",
                "singer": "Beyond",
                "webname": "制谱作者",
                "diaoString": "弹唱谱 • F调",
            },
            {
                "id": "tan8-other",
                "title": "晴天",
                "singer": "周杰伦",
                "webname": "其他作者",
                "diaoString": "和弦谱 • C调",
            },
        ]

    async def fail_ug(_: str) -> str:
        raise AssertionError("国内结果存在时不应调用国际备用源")

    monkeypatch.setattr(score_search, "_fetch_tan8", fake_tan8)
    monkeypatch.setattr(
        score_search,
        "_fetch_ultimate_guitar",
        fail_ug,
    )
    result = asyncio.run(
        score_search.search_scores("海阔天空", "Beyond")
    )

    assert result["provider"] == "弹琴吧"
    assert result["suggestions"][0]["id"] == "tan8-exact"
    assert result["suggestions"][0]["url"] == (
        "https://www.tan8.com/unionscore-tan8-exact.html"
    )
    assert result["libraries"][0]["name"] == "弹琴吧"
