"""Tool Discovery + Capability Registry persistence.

idea.md calls for an agent that *finds* new tools at runtime instead of
shipping a static catalog. This module implements:

  * `discover_tools(query)` — search GitHub repos (topic:mcp-server), npm
    (@modelcontextprotocol/* + "mcp-server"), and the public MCP registries
    that don't require auth. Returns a normalized list of candidates with
    suggested install commands and a coarse trust score.

  * `install_mcp_server(alias, command, args, env)` — spawns the candidate
    as an MCP server (via mcp_client.MCPManager), registers each tool it
    advertises, and appends the installation record to the persisted
    capability registry so we restore it on reboot.

  * `CapabilityRegistry` — JSON-on-disk store at
    `${AGUI_DATA_DIR}/capability_registry.json`. Survives restarts.

trustScore is a coarse 0..1 metric computed from author signal
(maintainer name = official @modelcontextprotocol > > random user),
GitHub stars, npm downloads, and whether the README mentions explicit
permission boundaries. Anything below ~0.45 should NOT auto-approve.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .llm import LLMClient, extract_json
from .mcp_client import MCPManager, MCPServerConfig


log = logging.getLogger("huxform.discovery")


_OFFICIAL_AUTHORS = {"modelcontextprotocol", "anthropic", "anthropics"}


# ---------------------------------------------------------------------------
# Capability registry — persistent record of every dynamically-added tool
# source (MCP server, OpenAPI spec, …). Survives restarts.
# ---------------------------------------------------------------------------


@dataclass
class InstalledMCP:
    alias: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    trust_score: float | None = None
    install_type: str = "npx"  # npx | uvx | docker | binary | remote
    source_url: str | None = None
    description: str | None = None


@dataclass
class InstalledOpenAPI:
    alias: str
    spec_url: str
    base_url: str | None = None
    auth_header_name: str | None = None
    auth_header_value: str | None = None
    trust_score: float | None = None


class CapabilityRegistry:
    """JSON-on-disk store for capabilities the agent has installed.

    On boot, the API hydrates this and re-spawns each MCP server / re-reads
    each OpenAPI spec, so the user's installed tools survive restarts.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.mcp: list[InstalledMCP] = []
        self.openapi: list[InstalledOpenAPI] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except Exception as exc:
            log.warning("CapabilityRegistry load failed: %s", exc)
            return
        for raw in data.get("mcp_servers") or []:
            try:
                self.mcp.append(InstalledMCP(
                    alias=raw["alias"],
                    command=raw["command"],
                    args=list(raw.get("args") or []),
                    env=dict(raw.get("env") or {}),
                    trust_score=raw.get("trust_score"),
                    install_type=raw.get("install_type") or "npx",
                    source_url=raw.get("source_url"),
                    description=raw.get("description"),
                ))
            except Exception as exc:
                log.warning("skipping malformed mcp entry: %s", exc)
        for raw in data.get("openapi_specs") or []:
            try:
                self.openapi.append(InstalledOpenAPI(
                    alias=raw["alias"],
                    spec_url=raw["spec_url"],
                    base_url=raw.get("base_url"),
                    auth_header_name=raw.get("auth_header_name"),
                    auth_header_value=raw.get("auth_header_value"),
                    trust_score=raw.get("trust_score"),
                ))
            except Exception as exc:
                log.warning("skipping malformed openapi entry: %s", exc)

    def save(self) -> None:
        data = {
            "mcp_servers": [asdict(x) for x in self.mcp],
            "openapi_specs": [asdict(x) for x in self.openapi],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add_mcp(self, entry: InstalledMCP) -> None:
        self.mcp = [m for m in self.mcp if m.alias != entry.alias]
        self.mcp.append(entry)
        self.save()

    def remove_mcp(self, alias: str) -> bool:
        before = len(self.mcp)
        self.mcp = [m for m in self.mcp if m.alias != alias]
        if len(self.mcp) != before:
            self.save()
            return True
        return False

    def add_openapi(self, entry: InstalledOpenAPI) -> None:
        self.openapi = [o for o in self.openapi if o.alias != entry.alias]
        self.openapi.append(entry)
        self.save()


# ---------------------------------------------------------------------------
# Discovery — search the public MCP ecosystem
# ---------------------------------------------------------------------------


def _trust_score(*, author: str, stars: int, downloads: int, has_official_marker: bool) -> float:
    score = 0.0
    if (author or "").lower() in _OFFICIAL_AUTHORS:
        score += 0.55
    if has_official_marker:
        score += 0.15
    # GitHub stars: log-ish ramp, capped
    if stars > 0:
        import math
        score += min(0.25, math.log10(max(stars, 1)) / 8)
    # npm downloads (weekly): same shape
    if downloads > 0:
        import math
        score += min(0.20, math.log10(max(downloads, 1)) / 8)
    return round(min(1.0, score), 3)


async def _gh_search(client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
    """GitHub repository search for `topic:mcp-server` + the query."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    q = f"topic:mcp-server {query}".strip()
    r = await client.get(
        "https://api.github.com/search/repositories",
        params={"q": q, "sort": "stars", "order": "desc", "per_page": min(limit, 30)},
        headers=headers,
        timeout=15.0,
    )
    if r.status_code == 403:
        log.warning("GitHub search rate-limited (401/403). Set GITHUB_TOKEN to raise the limit.")
        return []
    r.raise_for_status()
    items = (r.json() or {}).get("items") or []
    out: list[dict[str, Any]] = []
    for it in items:
        owner = (it.get("owner") or {}).get("login") or ""
        repo = it.get("name") or ""
        full = it.get("full_name") or f"{owner}/{repo}"
        stars = int(it.get("stargazers_count") or 0)
        score = _trust_score(
            author=owner,
            stars=stars,
            downloads=0,
            has_official_marker=("mcp-server" in (it.get("topics") or [])),
        )
        out.append({
            "source": "github",
            "id": full,
            "title": repo,
            "author": owner,
            "url": it.get("html_url"),
            "description": (it.get("description") or "")[:280],
            "stars": stars,
            "trust_score": score,
            "install_suggestion": _suggest_install(full, it),
        })
    return out


async def _npm_search(client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
    """npm registry search — picks up @modelcontextprotocol/* + community
    mcp-server-* packages."""
    text = f"mcp-server {query}".strip()
    r = await client.get(
        "https://registry.npmjs.org/-/v1/search",
        params={"text": text, "size": min(limit, 30), "popularity": 1.0},
        timeout=15.0,
    )
    r.raise_for_status()
    items = (r.json() or {}).get("objects") or []
    out: list[dict[str, Any]] = []
    for obj in items:
        pkg = obj.get("package") or {}
        name = pkg.get("name") or ""
        if not name:
            continue
        author = (pkg.get("publisher") or {}).get("username") or (pkg.get("scope") or "")
        downloads = int((obj.get("downloads") or {}).get("weekly") or 0) if isinstance(obj.get("downloads"), dict) else 0
        is_official = name.startswith("@modelcontextprotocol/")
        score = _trust_score(
            author=author,
            stars=0,
            downloads=downloads,
            has_official_marker=is_official,
        )
        out.append({
            "source": "npm",
            "id": name,
            "title": name,
            "author": author,
            "url": pkg.get("links", {}).get("npm") or f"https://www.npmjs.com/package/{name}",
            "description": (pkg.get("description") or "")[:280],
            "downloads_weekly": downloads,
            "trust_score": score,
            "install_suggestion": {
                "type": "npx",
                "command": "npx",
                "args": ["-y", name],
                "alias": _alias_from(name),
            },
        })
    return out


def _alias_from(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    base = re.sub(r"^mcp[-_]?server[-_]", "", base, flags=re.I)
    base = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_").lower()
    return base or "tool"


def _suggest_install(full: str, repo_meta: dict[str, Any]) -> dict[str, Any]:
    """Heuristic — guess install command from repo language / topics."""
    lang = (repo_meta.get("language") or "").lower()
    name = (repo_meta.get("name") or "").lower()
    # Common pattern: @modelcontextprotocol/server-foo lives in monorepo
    if "modelcontextprotocol" in (repo_meta.get("full_name") or "").lower():
        return {"type": "npx", "command": "npx", "args": ["-y", f"@modelcontextprotocol/server-{name.replace('server-','')}"], "alias": _alias_from(name)}
    if lang in {"typescript", "javascript"}:
        return {"type": "npx", "command": "npx", "args": ["-y", full], "alias": _alias_from(name)}
    if lang in {"python"}:
        return {"type": "uvx", "command": "uvx", "args": [full.split("/")[-1]], "alias": _alias_from(name)}
    return {"type": "manual", "command": "", "args": [], "alias": _alias_from(name), "note": f"clone {full} and read README"}


async def discover_tools(
    query: str,
    *,
    limit_per_source: int = 6,
    audit_top: int = 0,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Search MCP ecosystems and return a unified candidate list.

    When `audit_top > 0` and an `llm` is supplied, the top N candidates get an
    extra trust audit: their README is fetched and an LLM is asked to classify
    the permissions the server requests, then the result is folded into the
    coarse trust score (capped at 1.0).
    """
    headers = {"User-Agent": "HUXForm/0.3 (+https://github.com/agiwhitelist/HUXForm)"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        gh, npm = await asyncio.gather(
            _gh_search(client, query, limit_per_source),
            _npm_search(client, query, limit_per_source),
            return_exceptions=True,
        )
    candidates: list[dict[str, Any]] = []
    if isinstance(gh, list):
        candidates.extend(gh)
    if isinstance(npm, list):
        candidates.extend(npm)
    # Sort by trust score desc, then stars/downloads
    candidates.sort(
        key=lambda c: (
            -(c.get("trust_score") or 0.0),
            -(c.get("stars") or 0),
            -(c.get("downloads_weekly") or 0),
        )
    )
    candidates = candidates[: limit_per_source * 2]

    audited = 0
    if audit_top > 0 and llm is not None:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20.0) as client:
            for i, c in enumerate(candidates[: audit_top]):
                try:
                    readme = await _fetch_readme(client, c)
                    if not readme:
                        continue
                    audit = await _llm_audit_readme(llm, c, readme)
                    if not audit:
                        continue
                    c["llm_audit"] = audit
                    c["permissions"] = audit.get("permissions") or []
                    # Blend trust scores: keep upstream signal, but penalize / reward
                    # by README clarity. trust_score caps at 1.0.
                    upstream = float(c.get("trust_score") or 0.0)
                    classified = float(audit.get("trustworthiness") or 0.0)
                    c["trust_score"] = round(min(1.0, upstream * 0.6 + classified * 0.4 + 0.05), 3)
                    if audit.get("description_clean"):
                        c["description_clean"] = audit["description_clean"]
                    audited += 1
                except Exception as exc:  # pragma: no cover
                    log.debug("audit failed for %s: %s", c.get("id"), exc)
                    continue
        # Re-sort after auditing (top entries may have shifted)
        candidates.sort(
            key=lambda c: (
                -(c.get("trust_score") or 0.0),
                -(c.get("stars") or 0),
                -(c.get("downloads_weekly") or 0),
            )
        )

    return {
        "query": query,
        "candidates": candidates,
        "audited": audited,
        "gh_error": str(gh) if isinstance(gh, Exception) else None,
        "npm_error": str(npm) if isinstance(npm, Exception) else None,
    }


# ---------------------------------------------------------------------------
# README fetching + LLM audit (Capability Registry trust scoring)
# ---------------------------------------------------------------------------


async def _fetch_readme(client: httpx.AsyncClient, candidate: dict[str, Any]) -> str:
    """Pull the README markdown for a candidate. Returns the first 12 KB."""
    source = candidate.get("source")
    if source == "github":
        full = candidate.get("id") or ""
        for branch in ("main", "master"):
            url = f"https://raw.githubusercontent.com/{full}/{branch}/README.md"
            try:
                r = await client.get(url)
                if r.status_code == 200 and r.text.strip():
                    return r.text[:12_000]
            except Exception:
                continue
        return ""
    if source == "npm":
        name = candidate.get("id") or ""
        url = f"https://registry.npmjs.org/{name}"
        try:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return ""
        readme = data.get("readme") or ""
        if isinstance(readme, str) and readme:
            return readme[:12_000]
        # Fall back to the latest dist-tag's `readme` field if present
        latest = (data.get("dist-tags") or {}).get("latest")
        if latest and isinstance(data.get("versions"), dict):
            v = data["versions"].get(latest) or {}
            r2 = v.get("readme")
            if isinstance(r2, str):
                return r2[:12_000]
    return ""


_AUDIT_SYSTEM = (
    "You audit an MCP-server (or candidate MCP-server) for safety, based on its README. "
    "Output ONLY one JSON object — no prose, no markdown fence — with this schema:\n"
    "{\n"
    '  "description_clean": "<=200 chars summary of what the server actually does",\n'
    '  "permissions":       ["network" | "filesystem" | "shell" | "secret" | "destructive" | "read"],\n'
    '  "risk":              "read" | "network" | "write" | "destructive",\n'
    '  "trustworthiness":   0..1,\n'
    '  "red_flags":         ["short string", ...],\n'
    '  "looks_like_mcp":    true | false\n'
    "}\n"
    "Trustworthiness rubric:\n"
    "  0.9+ — official @modelcontextprotocol or Anthropic, well-known maintainer, clear permission boundary.\n"
    "  0.7  — community maintainer with explicit safety section, narrow scope, recent activity.\n"
    "  0.5  — generic README, scope is vague but not alarming.\n"
    "  <0.4 — vague scope, asks for broad permissions, no safety notes, or doesn't even look like an MCP server.\n"
    "If the README doesn't look like an MCP server at all (just generic library / unrelated repo), set looks_like_mcp=false and trustworthiness<0.3."
)


async def _llm_audit_readme(llm: LLMClient, candidate: dict[str, Any], readme: str) -> dict[str, Any] | None:
    user = (
        f"Candidate: {candidate.get('id')} (source={candidate.get('source')}, "
        f"author={candidate.get('author')}, stars={candidate.get('stars')}, "
        f"downloads_weekly={candidate.get('downloads_weekly')})\n\n"
        f"README excerpt (first ~12KB):\n```md\n{readme}\n```\n\nReturn the JSON now."
    )
    try:
        reply = await llm.complete(
            system=_AUDIT_SYSTEM,
            messages=[{"role": "user", "content": user}],
            temperature=0.2,
        )
        return extract_json(reply.text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Install — spawn an MCP server from a discovered candidate, register tools
# ---------------------------------------------------------------------------


async def install_mcp_server(
    *,
    manager: MCPManager,
    registry: CapabilityRegistry,
    alias: str,
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    trust_score: float | None = None,
    install_type: str = "npx",
    source_url: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Spawn a discovered MCP server, register its tools, persist the record."""
    if not alias or not re.match(r"^[a-zA-Z0-9_\-]+$", alias):
        raise ValueError(f"invalid alias: {alias!r}")
    if alias in manager.servers:
        raise RuntimeError(f"alias {alias!r} is already running")
    if command not in ("npx", "uvx", "docker", "node", "python", "python3"):
        if not shutil.which(command):
            raise FileNotFoundError(f"command not on PATH: {command}")

    cfg = MCPServerConfig(alias=alias, command=command, args=list(args or []), env=dict(env or {}))
    started = await manager.start_servers([cfg])

    entry = InstalledMCP(
        alias=alias, command=command, args=list(args or []), env=dict(env or {}),
        trust_score=trust_score, install_type=install_type,
        source_url=source_url, description=description,
    )
    registry.add_mcp(entry)

    server = manager.servers.get(alias)
    tools_advertised: list[str] = []
    if server:
        for name, t in manager.registry.tools.items():
            if name.startswith(f"mcp.{alias}."):
                tools_advertised.append(name)

    return {
        "ok": True,
        "alias": alias,
        "tools_registered": tools_advertised,
        "count": len(tools_advertised),
        "started": started,
    }


async def uninstall_mcp_server(
    *,
    manager: MCPManager,
    registry: CapabilityRegistry,
    alias: str,
) -> dict[str, Any]:
    """Stop a running MCP server, unregister its tools, drop it from the
    persistent capability registry."""
    if not alias or not re.match(r"^[a-zA-Z0-9_\-]+$", alias):
        raise ValueError(f"invalid alias: {alias!r}")

    removed_tools: list[str] = []
    server = manager.servers.get(alias)
    if server is not None:
        try:
            await server.stop()
        except Exception as exc:  # pragma: no cover
            log.warning("uninstall: server stop raised: %s", exc)
        manager.servers.pop(alias, None)

    prefix = f"mcp.{alias}."
    for name in list(manager.registry.tools.keys()):
        if name.startswith(prefix):
            manager.registry.unregister(name)
            removed_tools.append(name)

    persisted = registry.remove_mcp(alias)

    return {
        "ok": True,
        "alias": alias,
        "tools_removed": removed_tools,
        "persisted_record_removed": persisted,
        "server_was_running": server is not None,
    }


async def hydrate_installed(manager: MCPManager, registry: CapabilityRegistry) -> int:
    """On boot: start every MCP server in the persistent registry."""
    if not registry.mcp:
        return 0
    configs = [
        MCPServerConfig(alias=m.alias, command=m.command, args=list(m.args), env=dict(m.env))
        for m in registry.mcp
    ]
    return await manager.start_servers(configs)
