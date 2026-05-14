"""Web search + fetch providers.

Provider chain (highest priority wins, falls back on failure):

  1. Tavily      — needs TAVILY_API_KEY.   Best quality, paid after free tier.
  2. Brave       — needs BRAVE_API_KEY.    Free tier: 2000 req/mo.
  3. Serper      — needs SERPER_API_KEY.   Google results, free tier.
  4. DuckDuckGo  — zero-config. Free. HTML-scraping based.

DDG is always available so HUXForm has *real* web search out of the box.
We never fall back to "LLM hallucinates search results" — that is worse than
no search.

Response shape is uniform:

    {
      "provider": "ddg" | "tavily" | "brave" | "serper",
      "query":    str,
      "results":  [ { "title", "url", "snippet", "score"? } , ...  ],
      "answer":   optional str  (Tavily / Brave knowledge panel)
    }
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from html import unescape
from typing import Any
from urllib.parse import quote, urljoin, urlparse, parse_qs, unquote

import httpx

try:
    from ddgs import DDGS  # type: ignore
    _HAVE_DDGS = True
except Exception:  # pragma: no cover
    _HAVE_DDGS = False


log = logging.getLogger("huxform.web")


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _strip_tags(html: str) -> str:
    txt = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<style[^>]*>.*?</style>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = unescape(txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


# ---------------------------------------------------------------------------
# DuckDuckGo HTML scrape
# ---------------------------------------------------------------------------

_DDG_LITE = "https://lite.duckduckgo.com/lite/"


def _ddg_unwrap(href: str) -> str:
    """DDG GET responses wrap real URLs in /l/?uddg=<encoded>. Unwrap so
    callers get the real destination, not the redirector. POST responses
    on the lite endpoint already give direct URLs — this is a no-op for those."""
    try:
        u = urlparse(href if href.startswith("http") else urljoin("https://duckduckgo.com", href))
        if "duckduckgo.com" in u.netloc and u.path in ("/l/", "//l/"):
            qs = parse_qs(u.query)
            if "uddg" in qs and qs["uddg"]:
                return unquote(qs["uddg"][0])
    except Exception:
        pass
    return href


# Lite layout: each result is
#   <a rel="nofollow" href="URL" class="result-link">TITLE</a>
#   ...
#   <td class="result-snippet">SNIPPET</td>
_DDG_LITE_LINK_RE = re.compile(
    r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*class="[^"]*result-link[^"]*"[^>]*>(.+?)</a>',
    re.S | re.I,
)
_DDG_LITE_SNIPPET_RE = re.compile(
    r'<td[^>]+class="[^"]*result-snippet[^"]*"[^>]*>(.+?)</td>',
    re.S | re.I,
)


def _ddg_via_lib_sync(query: str, limit: int) -> list[dict[str, Any]]:
    """Call ddgs synchronously. Wrapped in to_thread for the async path."""
    out: list[dict[str, Any]] = []
    with DDGS() as d:  # type: ignore[name-defined]
        for x in d.text(query, max_results=limit):
            url = x.get("href") or x.get("url")
            if not url:
                continue
            out.append({
                "title": (x.get("title") or "").strip(),
                "url": url,
                "snippet": (x.get("body") or "").strip(),
            })
    return out


async def _ddg_search_lite(query: str, limit: int) -> list[dict[str, Any]]:
    """Direct /lite/ scrape — fallback when ddgs fails or isn't installed."""
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://lite.duckduckgo.com/",
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        r = await client.post(_DDG_LITE, data={"q": query, "kl": "wt-wt"})
        r.raise_for_status()
        html = r.text

    links: list[tuple[str, str]] = []
    for m in _DDG_LITE_LINK_RE.finditer(html):
        url = _ddg_unwrap(m.group(1))
        title = _strip_tags(m.group(2))
        if url.startswith("http") and title:
            links.append((url, title))
    snippets = [_strip_tags(m.group(1)) for m in _DDG_LITE_SNIPPET_RE.finditer(html)]

    out: list[dict[str, Any]] = []
    for i, (url, title) in enumerate(links):
        out.append({"title": title, "url": url, "snippet": snippets[i] if i < len(snippets) else ""})
        if len(out) >= limit:
            break
    return out


async def _ddg_search(query: str, limit: int = 8) -> dict[str, Any]:
    """DDG via `ddgs` library when available (it handles anti-bot cookies +
    vqd tokens, retrying across html/lite endpoints), else direct /lite/ scrape."""
    results: list[dict[str, Any]] = []
    last_err: Exception | None = None
    if _HAVE_DDGS:
        try:
            results = await asyncio.to_thread(_ddg_via_lib_sync, query, int(limit))
        except Exception as exc:  # pragma: no cover - library hiccups
            last_err = exc
            log.warning("ddgs library call failed: %s", exc)
    if not results:
        try:
            results = await _ddg_search_lite(query, int(limit))
        except Exception as exc:
            last_err = exc
            log.warning("DDG lite scrape failed: %s", exc)
    out: dict[str, Any] = {"provider": "ddg", "query": query, "results": results}
    if not results and last_err is not None:
        out["error"] = str(last_err)
    return out


# ---------------------------------------------------------------------------
# SearXNG public instance (JSON) — last-resort fallback if DDG is throttled
# ---------------------------------------------------------------------------

_SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://search.disroot.org",
    "https://baresearch.org",
]


async def _searxng_search(query: str, limit: int) -> dict[str, Any]:
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    last_err: Exception | None = None
    for base in _SEARXNG_INSTANCES:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
                r = await client.get(
                    f"{base}/search",
                    params={"q": query, "format": "json", "safesearch": 0},
                )
                r.raise_for_status()
                data = r.json()
            items = data.get("results") or []
            results = [
                {
                    "title": x.get("title"),
                    "url": x.get("url"),
                    "snippet": x.get("content"),
                    "score": x.get("score"),
                }
                for x in items[:limit]
            ]
            if results:
                return {"provider": f"searxng:{urlparse(base).netloc}", "query": query, "results": results}
        except Exception as exc:
            last_err = exc
            log.debug("SearXNG %s failed: %s", base, exc)
            continue
    return {"provider": "searxng", "query": query, "results": [], "error": str(last_err) if last_err else "all instances failed"}


# ---------------------------------------------------------------------------
# Tavily / Brave / Serper
# ---------------------------------------------------------------------------


async def _tavily_search(api_key: str, query: str, limit: int) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": int(limit),
                "search_depth": "basic",
                "include_answer": True,
            },
        )
        r.raise_for_status()
        data = r.json()
    results = [
        {
            "title": x.get("title"),
            "url": x.get("url"),
            "snippet": x.get("content"),
            "score": x.get("score"),
        }
        for x in (data.get("results") or [])
    ]
    return {
        "provider": "tavily",
        "query": query,
        "results": results,
        "answer": data.get("answer"),
    }


async def _brave_search(api_key: str, query: str, limit: int) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": int(limit)},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
        r.raise_for_status()
        data = r.json()
    items = ((data.get("web") or {}).get("results")) or []
    results = [
        {
            "title": x.get("title"),
            "url": x.get("url"),
            "snippet": x.get("description"),
            "score": None,
        }
        for x in items
    ]
    info = data.get("infobox") or {}
    answer = info.get("long_desc") or info.get("description")
    return {"provider": "brave", "query": query, "results": results, "answer": answer}


async def _serper_search(api_key: str, query: str, limit: int) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": int(limit)},
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    items = data.get("organic") or []
    results = [
        {
            "title": x.get("title"),
            "url": x.get("link"),
            "snippet": x.get("snippet"),
            "score": None,
        }
        for x in items[:limit]
    ]
    answer = (data.get("answerBox") or {}).get("answer") or (data.get("knowledgeGraph") or {}).get("description")
    return {"provider": "serper", "query": query, "results": results, "answer": answer}


# ---------------------------------------------------------------------------
# Public search entry point — picks best provider, falls back to DDG.
# ---------------------------------------------------------------------------


async def web_search(query: str, limit: int = 6) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"provider": "noop", "query": "", "results": []}

    tavily = os.environ.get("TAVILY_API_KEY") or ""
    brave = os.environ.get("BRAVE_API_KEY") or ""
    serper = os.environ.get("SERPER_API_KEY") or ""

    providers: list[tuple[str, Any]] = []
    if tavily:
        providers.append(("tavily", lambda: _tavily_search(tavily, query, limit)))
    if brave:
        providers.append(("brave", lambda: _brave_search(brave, query, limit)))
    if serper:
        providers.append(("serper", lambda: _serper_search(serper, query, limit)))
    providers.append(("ddg", lambda: _ddg_search(query, limit)))
    providers.append(("searxng", lambda: _searxng_search(query, limit)))

    last_err: Exception | None = None
    for name, fn in providers:
        try:
            res = await fn()
            if res.get("results"):
                return res
        except Exception as exc:
            last_err = exc
            log.warning("web search via %s failed: %s", name, exc)
            continue

    return {
        "provider": "none",
        "query": query,
        "results": [],
        "error": str(last_err) if last_err else "no results",
    }


# ---------------------------------------------------------------------------
# web.fetch — pull a URL and return readable text + headers
# ---------------------------------------------------------------------------


async def web_fetch(url: str, *, max_bytes: int = 800_000, extract_links: bool = False) -> dict[str, Any]:
    if not url or not isinstance(url, str):
        raise ValueError("url is required")
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")

    headers = {"User-Agent": _UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=headers) as client:
        r = await client.get(url)
        ctype = r.headers.get("content-type", "")
        raw = r.content[:max_bytes]
        status = r.status_code
        final_url = str(r.url)

    out: dict[str, Any] = {
        "url": final_url,
        "status": status,
        "content_type": ctype,
        "bytes": len(raw),
    }

    if "application/json" in ctype:
        try:
            import json
            out["json"] = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            out["text"] = raw.decode("utf-8", errors="replace")
        return out

    if any(t in ctype for t in ("text/html", "application/xhtml")):
        html = raw.decode("utf-8", errors="replace")
        # title
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        out["title"] = _strip_tags(m.group(1)) if m else None
        # meta description
        m = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.I,
        )
        out["description"] = m.group(1) if m else None
        out["text"] = _strip_tags(html)[:50_000]
        if extract_links:
            links: list[dict[str, str]] = []
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
                href = m.group(1)
                if href.startswith("/") or href.startswith(("http://", "https://")):
                    links.append({
                        "url": urljoin(final_url, href),
                        "text": _strip_tags(m.group(2))[:120],
                    })
                if len(links) >= 80:
                    break
            out["links"] = links
        return out

    if any(t in ctype for t in ("text/", "application/xml", "application/javascript")):
        out["text"] = raw.decode("utf-8", errors="replace")
        return out

    # Unknown / binary — return base64 so callers can pass to other tools
    import base64
    out["base64"] = base64.b64encode(raw).decode("ascii")
    return out
