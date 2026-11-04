"""通过公开音乐目录查询市面可用的伴奏与纯音乐版本。"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

import httpx


ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
INSTRUMENT_TERMS = {
    "vocals": "vocals",
    "drums": "drums",
    "bass": "bass",
    "guitar": "guitar",
    "piano": "piano",
    "other": "instruments",
}
ACCOMPANIMENT_TERMS = (
    "backing track",
    "backing tracks",
    "karaoke",
    "instrumental",
    "minus ",
    "without ",
    "playback",
    "伴奏",
    "伴唱",
    "纯音乐",
)


async def _fetch_itunes(query: str, limit: int) -> list[dict[str, Any]]:
    """请求单个 iTunes 搜索词，返回歌曲条目。"""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=True,
        headers={"User-Agent": "Fretline/0.1 (online accompaniment search)"},
    ) as client:
        response = await client.get(
            ITUNES_SEARCH_URL,
            params={
                "term": query,
                "entity": "song",
                "limit": limit,
                "country": "us",
                "lang": "en_us",
            },
        )
        response.raise_for_status()
        payload = response.json()
    results = payload.get("results", [])
    return [item for item in results if isinstance(item, dict)]


def _safe_https_url(value: Any, allowed_hosts: set[str]) -> str | None:
    """只保留来自 Apple 官方域名的 HTTPS 链接。"""
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        return None
    return value


def _match_kind(item: dict[str, Any]) -> str | None:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("trackName", "collectionName", "artistName")
    ).lower()
    if "karaoke" in haystack or "伴唱" in haystack:
        return "Karaoke"
    if "minus " in haystack or "without " in haystack:
        return "Minus One"
    if "backing" in haystack or "伴奏" in haystack:
        return "Backing Track"
    if "instrumental" in haystack or "纯音乐" in haystack:
        return "Instrumental"
    return None


def _relevance_score(
    item: dict[str, Any],
    title: str,
    artist: str,
    remove_stems: list[str],
) -> int:
    """按照伴奏特征和目标乐器对搜索结果排序。"""
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("trackName", "collectionName", "artistName")
    ).lower()
    score = 0
    if "backing" in haystack:
        score += 7
    if "karaoke" in haystack:
        score += 6
    if "instrumental" in haystack or "纯音乐" in haystack:
        score += 5
    if "minus " in haystack or "without " in haystack:
        score += 5
    if "伴奏" in haystack:
        score += 6
    for stem in remove_stems:
        term = INSTRUMENT_TERMS.get(stem)
        if term and term.lower() in haystack:
            score += 5
    if artist.strip() and artist.strip().lower() in haystack:
        score += 2
    title_tokens = [
        token
        for token in re.split(r"[\s\-_/]+", title.lower())
        if len(token) >= 2
    ]
    score += sum(1 for token in title_tokens if token in haystack)
    return score


def _normalize_suggestion(item: dict[str, Any], score: int) -> dict[str, Any] | None:
    kind = _match_kind(item)
    if kind is None:
        return None
    web_url = _safe_https_url(
        item.get("trackViewUrl"),
        {"music.apple.com"},
    )
    if web_url is None:
        return None
    preview_url = _safe_https_url(
        item.get("previewUrl"),
        {"audio-ssl.itunes.apple.com"},
    )
    artwork_url = _safe_https_url(
        item.get("artworkUrl100"),
        {"is1-ssl.mzstatic.com", "is2-ssl.mzstatic.com", "is3-ssl.mzstatic.com"},
    )
    track_id = item.get("trackId")
    if track_id is None:
        return None
    return {
        "id": str(track_id),
        "title": str(item.get("trackName") or "未命名伴奏"),
        "artist": str(item.get("artistName") or "未知艺人"),
        "album": str(item.get("collectionName") or ""),
        "kind": kind,
        "url": web_url,
        "preview_url": preview_url,
        "artwork_url": artwork_url,
        "relevance": score,
    }


async def search_market(
    title: str,
    artist: str,
    remove_stems: list[str],
    limit: int = 8,
) -> dict[str, Any]:
    """并行搜索伴奏关键词，过滤无关原曲后按相关度返回。"""
    clean_title = title.strip()
    clean_artist = artist.strip()
    base = " ".join(part for part in (clean_title, clean_artist) if part)
    queries = [
        f"{base} backing track",
        f"{base} karaoke",
        f"{base} instrumental",
    ]
    targeted_stems = [
        stem for stem in dict.fromkeys(remove_stems)
        if stem in INSTRUMENT_TERMS
    ]
    if targeted_stems:
        instrument_terms = " ".join(
            INSTRUMENT_TERMS[stem] for stem in targeted_stems
        )
        queries.append(f"{base} backing track minus {instrument_terms}")

    responses = await asyncio.gather(
        *(_fetch_itunes(query, limit) for query in queries),
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
            score = _relevance_score(item, clean_title, clean_artist, targeted_stems)
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
        "provider": "Apple Music / iTunes Search",
        "queries": queries,
        "suggestions": suggestions,
    }
