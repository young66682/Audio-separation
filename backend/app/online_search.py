"""通过国内音乐目录查询市面可用的伴奏与纯音乐版本。"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

import httpx


NETEASE_SEARCH_URL = "https://music.163.com/api/cloudsearch/pc"
NETEASE_SONG_URL = "https://music.163.com/#/song?id={song_id}"
NETEASE_PREVIEW_URL = (
    "https://music.163.com/song/media/outer/url?id={song_id}.mp3"
)
NETEASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
}
INSTRUMENT_TERMS = {
    "vocals": ("人声", "伴唱"),
    "drums": ("鼓",),
    "bass": ("贝斯",),
    "guitar": ("吉他",),
    "piano": ("钢琴",),
    "other": ("器乐",),
}


async def _fetch_netease(query: str, limit: int) -> list[dict[str, Any]]:
    """请求单个网易云音乐搜索词，返回歌曲条目。"""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=True,
        headers=NETEASE_HEADERS,
    ) as client:
        response = await client.post(
            NETEASE_SEARCH_URL,
            data={
                "s": query,
                "type": 1,
                "offset": 0,
                "total": "true",
                "limit": limit,
            },
        )
        response.raise_for_status()
        payload = response.json()
    if payload.get("code") not in {None, 200}:
        raise RuntimeError("网易云音乐搜索接口返回异常")
    results = (payload.get("result") or {}).get("songs", [])
    return [item for item in results if isinstance(item, dict)]


def _safe_https_url(
    value: Any,
    allowed_hosts: set[str],
    allowed_suffixes: tuple[str, ...] = (),
) -> str | None:
    """只保留可信域名，并统一转换为 HTTPS。"""
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    allowed = hostname in allowed_hosts or any(
        hostname.endswith(f".{suffix}") for suffix in allowed_suffixes
    )
    if parsed.scheme not in {"http", "https"} or not allowed:
        return None
    return parsed._replace(scheme="https").geturl()


def _item_haystack(item: dict[str, Any]) -> str:
    album = item.get("al") or item.get("album") or {}
    artists = item.get("ar") or item.get("artists") or []
    aliases = item.get("alia") or []
    return " ".join(
        [
            str(item.get("name") or item.get("trackName") or ""),
            str(album.get("name") or item.get("collectionName") or ""),
            *(
                str(artist.get("name") or "")
                for artist in artists
                if isinstance(artist, dict)
            ),
            *(str(alias) for alias in aliases),
        ]
    ).lower()


def _match_kind(item: dict[str, Any]) -> str | None:
    haystack = _item_haystack(item)
    if "karaoke" in haystack or "伴唱" in haystack:
        return "伴唱"
    if any(
        term in haystack
        for term in (
            "minus ",
            "without ",
            "off vocal",
            "无人声",
            "去人声",
        )
    ):
        return "无人声"
    if "backing" in haystack or "伴奏" in haystack:
        return "伴奏"
    if "instrumental" in haystack or "纯音乐" in haystack:
        return "纯音乐"
    return None


def _relevance_score(
    item: dict[str, Any],
    title: str,
    artist: str,
    remove_stems: list[str],
) -> int:
    """按照伴奏特征和目标乐器对搜索结果排序。"""
    haystack = _item_haystack(item)
    score = 0
    if "伴奏" in haystack:
        score += 8
    if "纯音乐" in haystack or "instrumental" in haystack:
        score += 7
    if "伴唱" in haystack or "karaoke" in haystack:
        score += 6
    if any(
        term in haystack
        for term in (
            "minus ",
            "without ",
            "off vocal",
            "无人声",
            "去人声",
        )
    ):
        score += 6
    if "backing" in haystack:
        score += 5
    for stem in remove_stems:
        terms = INSTRUMENT_TERMS.get(stem, ())
        if any(term.lower() in haystack for term in terms):
            score += 5
    if artist.strip() and artist.strip().lower() in haystack:
        score += 2
    if title.strip() and title.strip().lower() in haystack:
        score += 2
    title_tokens = [
        token
        for token in re.split(r"[\s\-_/]+", title.lower())
        if len(token) >= 2
    ]
    score += sum(1 for token in title_tokens if token in haystack)
    privilege = item.get("privilege") or {}
    if int(privilege.get("pl") or 0) > 0:
        score += 1
    return score


def _normalize_suggestion(
    item: dict[str, Any],
    score: int,
) -> dict[str, Any] | None:
    kind = _match_kind(item)
    if kind is None:
        return None
    track_id = item.get("id")
    if track_id is None:
        return None
    album = item.get("al") or item.get("album") or {}
    artists = item.get("ar") or item.get("artists") or []
    artist = " / ".join(
        str(value.get("name") or "")
        for value in artists
        if isinstance(value, dict) and value.get("name")
    )
    privilege = item.get("privilege") or {}
    is_playable = int(privilege.get("pl") or 0) > 0
    artwork_url = _safe_https_url(
        album.get("picUrl"),
        set(),
        ("music.126.net",),
    )
    return {
        "id": str(track_id),
        "title": str(
            item.get("name") or item.get("trackName") or "未命名伴奏"
        ),
        "artist": artist or "未知艺人",
        "album": str(album.get("name") or item.get("collectionName") or ""),
        "kind": kind,
        "url": NETEASE_SONG_URL.format(song_id=track_id),
        "preview_url": (
            NETEASE_PREVIEW_URL.format(song_id=track_id)
            if is_playable
            else None
        ),
        "artwork_url": artwork_url,
        "relevance": score,
    }


async def search_market(
    title: str,
    artist: str,
    remove_stems: list[str],
    limit: int = 8,
) -> dict[str, Any]:
    """并行搜索国内伴奏关键词，过滤无关原曲后按相关度返回。"""
    clean_title = title.strip()
    clean_artist = artist.strip()
    base = " ".join(part for part in (clean_title, clean_artist) if part)
    queries = [
        f"{base} 伴奏",
        f"{base} 纯音乐",
        f"{base} 伴唱",
        f"{base} instrumental",
    ]
    targeted_stems = [
        stem
        for stem in dict.fromkeys(remove_stems)
        if stem in INSTRUMENT_TERMS
    ]
    if targeted_stems:
        instrument_terms = " ".join(
            INSTRUMENT_TERMS[stem][0] for stem in targeted_stems
        )
        queries.append(f"{base} 伴奏 无{instrument_terms}")
    queries = list(dict.fromkeys(queries))

    responses = await asyncio.gather(
        *(_fetch_netease(query, limit) for query in queries),
        return_exceptions=True,
    )
    successful = [items for items in responses if isinstance(items, list)]
    if not successful:
        first_error = next(
            (error for error in responses if isinstance(error, Exception)),
            None,
        )
        raise RuntimeError("联网伴奏查询暂不可用") from first_error

    deduplicated: dict[str, dict[str, Any]] = {}
    for items in successful:
        for item in items:
            score = _relevance_score(
                item,
                clean_title,
                clean_artist,
                targeted_stems,
            )
            suggestion = _normalize_suggestion(item, score)
            if suggestion is None or suggestion["relevance"] <= 0:
                continue
            current = deduplicated.get(suggestion["id"])
            if current is None or suggestion["relevance"] > current["relevance"]:
                deduplicated[suggestion["id"]] = suggestion

    suggestions = sorted(
        deduplicated.values(),
        key=lambda item: (
            -int(item["relevance"]),
            item["title"].lower(),
        ),
    )[:limit]
    return {
        "provider": "网易云音乐 · 国内搜索",
        "queries": queries,
        "suggestions": suggestions,
    }
