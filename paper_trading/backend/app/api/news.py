"""
News feed API — aggregated RSS from major crypto publications.
GET /api/news?limit=30&source=CoinDesk
"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from fastapi import APIRouter, Query

router = APIRouter()

RSS_FEEDS = [
    ("CoinDesk",       "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",  "https://cointelegraph.com/rss"),
    ("The Block",      "https://www.theblock.co/rss.xml"),
    ("Decrypt",        "https://decrypt.co/feed"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
]

_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}


def _parse_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return s


async def _fetch_feed(
    client: httpx.AsyncClient, source: str, url: str
) -> list[dict]:
    try:
        r = await client.get(url, timeout=8.0, follow_redirects=True)
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception:
        return []

    items = []
    for item in root.iter("item"):
        def _t(tag: str) -> str | None:
            el = item.find(tag)
            return el.text if el is not None else None

        title = _t("title")
        link = _t("link")
        pub_date = _parse_date(_t("pubDate"))
        description = _t("description") or ""
        description = re.sub(r"<[^>]+>", "", description).strip()[:300]

        if title and link:
            items.append({
                "source": source,
                "title": title.strip(),
                "url": link.strip(),
                "published_at": pub_date,
                "summary": description or None,
            })

    return items


@router.get("/news")
async def get_news(
    limit: int = Query(40, ge=1, le=100),
    source: str | None = Query(None, description="Filter by source name"),
):
    """
    Aggregated crypto news from major RSS feeds, sorted by publish date descending.
    """
    feeds_to_fetch = [
        (name, url)
        for name, url in RSS_FEEDS
        if source is None or name.lower() == source.lower()
    ]

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; QuantSystem/1.0)"},
        timeout=10.0,
    ) as client:
        results = await asyncio.gather(
            *[_fetch_feed(client, name, url) for name, url in feeds_to_fetch],
            return_exceptions=True,
        )

    all_items: list[dict] = []
    sources_ok: list[str] = []
    sources_err: list[str] = []

    for (name, _), result in zip(feeds_to_fetch, results):
        if isinstance(result, Exception) or result is None:
            sources_err.append(name)
        else:
            all_items.extend(result)
            if result:
                sources_ok.append(name)
            else:
                sources_err.append(name)

    # Sort by publish date, most recent first
    def _sort_key(item: dict) -> str:
        return item.get("published_at") or "0"

    all_items.sort(key=_sort_key, reverse=True)

    return {
        "items": all_items[:limit],
        "total": len(all_items),
        "sources_ok": sources_ok,
        "sources_err": sources_err,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
