"""公开曲谱站点搜索与 Ultimate Guitar 结果解析。"""

from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx


ULTIMATE_GUITAR_SEARCH_URL = (
    "https://www.ultimate-guitar.com/search.php?search_type=title&value={query}"
)
SCORE_TYPES = {
    "Tabs": 5,
    "Tab": 5,
    "Chords": 4,
    "Power": 3,
    "Bass": 2,
    "Ukulele": 2,
    "Drums": 1,
}
TAN8_SEARCH_PAGE = "https://www.tan8.com/codeindex.php"
TAN8_FIXED_PARAMS = {
    "d": "api",
    "c": "dynamicTemplate",
    "m": "get_view_info",
    "yuepu_type": "",
    "album_id": "0",
    "seriesId": "0",
    "orderBy": "0",
    "level": "0",
    "keys": "0",
    "accStatus": "0",
    "score_type": "0",
    "dataType": "1",
    "sort1": "0",
    "sort2": "0",
    "sort3": "0",
    "sort4": "0",
    "title": "",
    "singer": "",
    "squareType": "",
    "scoreType": "",
    "webScoreType": "",
    "muban_data_ver": "13",
    "apptype": "2",
    "device": "android",
    "dataVersion": "2023",
    "app_version": "8.7",
    "platform": "android",
    "app_type": "2",
}


async def _fetch_ultimate_guitar(query: str) -> str:
    """请求 Ultimate Guitar 搜索页面。"""
    url = ULTIMATE_GUITAR_SEARCH_URL.format(query=quote_plus(query))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Fretline/0.1)"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _fetch_tan8(title: str, limit: int) -> list[dict[str, Any]]:
    """调用弹琴吧公开搜索接口，优先查询中文吉他谱。"""
    params = {
        **TAN8_FIXED_PARAMS,
        "instrumentType": "7",
        "type": "newSearch_unionscore_song",
        "model_id": "1499",
        "guolv_id1": title,
        "limit": str(min(20, max(limit, 10))),
        "start": "0",
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Fretline/0.1)"},
    ) as client:
        response = await client.get(TAN8_SEARCH_PAGE, params=params)
        response.raise_for_status()
        payload = response.json()
    result = payload.get("data", {}).get("result", [])
    if not isinstance(result, list):
        raise RuntimeError("弹琴吧搜索结果格式不正确")
    return [item for item in result if isinstance(item, dict)]


def _extract_page_data(page: str) -> dict[str, Any]:
    """从 HTML 中读取搜索页内嵌的 JSON 数据。"""
    candidates = re.findall(r'data-content="([^"]+)"', page)
    if not candidates:
        raise RuntimeError("曲谱搜索页面格式已变化")
    payload = html.unescape(max(candidates, key=len))
    data = json.loads(payload)
    result = (
        data.get("store", {})
        .get("page", {})
        .get("data", {})
        .get("results", [])
    )
    if not isinstance(result, list):
        raise RuntimeError("曲谱搜索结果格式不正确")
    return {"results": result}


def _safe_tab_url(value: Any) -> str | None:
    """仅接受 Ultimate Guitar 的 HTTPS 曲谱详情链接。"""
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "tabs.ultimate-guitar.com":
        return None
    return value


def _normalize_search_text(value: Any) -> str:
    """统一全半角、大小写和标点，便于比较中英文歌名。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def _title_relevance(item: dict[str, Any], title: str) -> float:
    """歌名匹配的权重必须显著高于谱型和票数。"""
    target = _normalize_search_text(title)
    if not target:
        return 0.0
    candidates = {
        _normalize_search_text(item.get("song_name")),
        _normalize_search_text(item.get("localized_song_name")),
    }
    candidates.discard("")
    best = 0.0
    for candidate in candidates:
        if candidate == target:
            return 1_000_000.0
        if target in candidate:
            length_ratio = len(target) / max(1, len(candidate))
            best = max(best, 700_000.0 + length_ratio * 50_000)
        elif candidate in target and len(candidate) >= 2:
            best = max(best, 550_000.0)
        elif min(len(target), len(candidate)) >= 4:
            similarity = SequenceMatcher(None, target, candidate).ratio()
            if similarity >= 0.62:
                best = max(best, similarity * 300_000)
    return best


def _artist_relevance(item: dict[str, Any], artist: str) -> float:
    """艺人匹配作为歌曲名匹配之后的次级排序依据。"""
    target = _normalize_search_text(artist)
    if not target:
        return 0.0
    candidates = {
        _normalize_search_text(item.get("artist_name")),
        _normalize_search_text(item.get("localized_artist_name")),
    }
    candidates.discard("")
    if target in candidates:
        return 120_000.0
    if any(target in candidate or candidate in target for candidate in candidates):
        return 80_000.0
    return 0.0


def _score_rank(
    item: dict[str, Any],
    title: str,
    artist: str,
) -> float:
    """按歌曲名、艺人、谱型和用户评分综合排序。"""
    kind = str(item.get("type") or "")
    kind_score = SCORE_TYPES.get(kind, 0)
    try:
        rating = float(item.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0.0
    try:
        votes = max(0, int(item.get("votes") or 0))
    except (TypeError, ValueError):
        votes = 0
    return (
        _title_relevance(item, title)
        + _artist_relevance(item, artist)
        + kind_score * 250
        + rating * 200
        + math.log10(votes + 1) * 10
    )


def _normalize_score(item: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(item.get("type") or "")
    if kind not in SCORE_TYPES:
        return None
    tab_url = _safe_tab_url(item.get("tab_url"))
    # Ultimate Guitar 的普通曲谱使用 id，推广条目使用 tab_id。
    tab_id = item.get("tab_id") or item.get("id")
    if tab_url is None or tab_id is None:
        return None
    try:
        rating = round(float(item.get("rating") or 0), 2)
    except (TypeError, ValueError):
        rating = 0.0
    try:
        votes = max(0, int(item.get("votes") or 0))
    except (TypeError, ValueError):
        votes = 0
    return {
        "id": str(tab_id),
        "title": str(item.get("song_name") or "未命名曲谱"),
        "artist": str(item.get("artist_name") or "未知艺人"),
        "type": kind,
        "version": str(item.get("version") or ""),
        "rating": rating,
        "votes": votes,
        "url": tab_url,
        "provider": "Ultimate Guitar",
    }


def _library_links(query: str) -> list[dict[str, str]]:
    encoded = quote_plus(query)
    return [
        {
            "name": "弹琴吧",
            "url": f"https://www.tan8.com/search.html?keyword={encoded}",
        },
        {
            "name": "Ultimate Guitar",
            "url": ULTIMATE_GUITAR_SEARCH_URL.format(query=encoded),
        },
        {
            "name": "Songsterr",
            "url": f"https://www.songsterr.com/?pattern={encoded}",
        },
        {
            "name": "MuseScore",
            "url": f"https://musescore.com/sheetmusic?text={encoded}",
        },
    ]


def _normalize_tan8(
    item: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    """转换弹琴吧曲谱字段，并生成安全详情链接。"""
    score_id = item.get("id")
    if not isinstance(score_id, str) or not score_id:
        return None
    diao = str(item.get("diaoString") or "")
    score_type = diao.split("•", 1)[0].strip() or "吉他谱"
    return {
        "id": score_id,
        "title": str(item.get("title") or "未命名曲谱"),
        "artist": str(item.get("singer") or "未知艺人"),
        "type": score_type,
        "version": str(item.get("webname") or ""),
        "rating": 0.0,
        "votes": 0,
        "url": f"https://www.tan8.com/unionscore-{score_id}.html",
        "provider": "弹琴吧",
        "meta": diao,
        "_order": index,
    }


def _rank_tan8(
    item: dict[str, Any],
    normalized: dict[str, Any],
    title: str,
    artist: str,
) -> float:
    """国内接口已按相关度返回，排序时保留其原始顺序。"""
    return (
        _title_relevance(item, title)
        + _artist_relevance(item, artist)
        - int(normalized["_order"]) * 0.001
    )


async def search_scores(
    title: str,
    artist: str,
    limit: int = 8,
) -> dict[str, Any]:
    """搜索现有吉他谱，返回具体曲谱页面与备用谱库入口。"""
    base = " ".join(
        part for part in (title.strip(), artist.strip()) if part
    )
    provider = "弹琴吧"
    suggestions: list[dict[str, Any]] = []
    try:
        tan8_results = await _fetch_tan8(title.strip(), limit)
    except (httpx.HTTPError, ValueError, RuntimeError):
        tan8_results = []

    if tan8_results:
        ranked_tan8: list[dict[str, Any]] = []
        seen_tan8: set[str] = set()
        for index, item in enumerate(tan8_results):
            suggestion = _normalize_tan8(item, index)
            if suggestion is None or suggestion["id"] in seen_tan8:
                continue
            seen_tan8.add(suggestion["id"])
            suggestion["_rank"] = _rank_tan8(
                item,
                suggestion,
                title,
                artist,
            )
            ranked_tan8.append(suggestion)
        suggestions = sorted(
            ranked_tan8,
            key=lambda item: -float(item["_rank"]),
        )[:limit]
    else:
        # 国内接口不可用时回退到国际曲谱库。
        page = await _fetch_ultimate_guitar(base)
        parsed = _extract_page_data(page)
        provider = "Ultimate Guitar（国际备用）"
        deduplicated: dict[str, dict[str, Any]] = {}
        for item in parsed["results"]:
            if not isinstance(item, dict):
                continue
            suggestion = _normalize_score(item)
            if suggestion is None:
                continue
            rank = _score_rank(item, title, artist)
            current = deduplicated.get(suggestion["id"])
            if current is None or rank > float(current["_rank"]):
                suggestion["_rank"] = rank
                deduplicated[suggestion["id"]] = suggestion
        suggestions = sorted(
            deduplicated.values(),
            key=lambda item: (-float(item["_rank"]), item["title"].lower()),
        )[:limit]

    for item in suggestions:
        item.pop("_rank", None)
        item.pop("_order", None)

    return {
        "provider": provider,
        "query": base,
        "suggestions": suggestions,
        "libraries": _library_links(base),
    }
