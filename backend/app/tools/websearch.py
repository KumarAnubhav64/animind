"""Web search tool: DuckDuckGo text search, no API key required."""

import logging
from typing import Any

logger = logging.getLogger("animind.search")

MAX_SNIPPETS = 10
_SNIPPET_BODY_MAX = 300


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search DuckDuckGo and return title/href/body snippets (best-effort).

    Returns an empty list on any failure so the pipeline degrades gracefully
    (the Researcher just skips web enrichment).
    """
    try:
        from ddgs import DDGS
    except Exception as error:  # noqa: BLE001
        logger.warning("ddgs not available: %s", error)
        return []

    try:
        with DDGS() as client:
            raw = list(client.text(query, max_results=max_results))
    except Exception as error:  # noqa: BLE001
        logger.warning("web search failed for %r: %s", query, error)
        return []

    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        href = str(item.get("href") or item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not href:
            continue
        out.append({
            "title": title[:150],
            "href": href[:300],
            "body": body[:_SNIPPET_BODY_MAX],
        })
        if len(out) >= max_results:
            break
    return out


def search_multi(queries: list[str], per_query: int = 4) -> list[dict[str, str]]:
    """Run several queries and deduplicate results by URL."""
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for query in queries:
        for item in web_search(query, max_results=per_query):
            href = item["href"]
            if href in seen:
                continue
            seen.add(href)
            results.append(item)
            if len(results) >= MAX_SNIPPETS:
                return results
    return results
