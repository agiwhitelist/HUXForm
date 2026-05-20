"""OSV.dev dependency vulnerability scanner.

OSV.dev (https://osv.dev) is Google's open vulnerability database. It mirrors
GHSA, PyPA, RustSec, npm advisories and more behind one free, unauthenticated
REST API. We use two endpoints:

  POST /v1/querybatch  — map a list of (package, version) to vulnerability IDs
  GET  /v1/vulns/{id}  — pull the full record (aliases, severity, fixed range)

This is the builtin that lets the Researcher answer "is this dependency tree
vulnerable?" without discovering and installing a third-party MCP server.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx


log = logging.getLogger("huxform.osv")

_QUERYBATCH = "https://api.osv.dev/v1/querybatch"
_VULN = "https://api.osv.dev/v1/vulns/"

# Same opt-in proxy the rest of the research path honors (see web_search.py).
_WEB_PROXY = os.environ.get("AGUI_WEB_PROXY") or None

# Cap how many full vuln records we hydrate — keeps the call bounded and the
# research state small enough to embed in the codegen prompt.
_MAX_DETAIL = 24


def _severity_label(record: dict[str, Any]) -> str:
    """Best-effort severity from a GHSA/OSV record."""
    db = record.get("database_specific") or {}
    sev = db.get("severity")
    if isinstance(sev, str) and sev:
        return sev.upper()
    for aff in record.get("affected") or []:
        ds = aff.get("database_specific") or {}
        s = ds.get("severity")
        if isinstance(s, str) and s:
            return s.upper()
    # CVSS vector present but no label — mark it so the UI still flags it.
    if record.get("severity"):
        return "RATED"
    return "UNKNOWN"


def _fixed_versions(record: dict[str, Any]) -> list[str]:
    """Pull every 'fixed' event from the affected ranges."""
    out: list[str] = []
    for aff in record.get("affected") or []:
        for rng in aff.get("ranges") or []:
            for ev in rng.get("events") or []:
                fixed = ev.get("fixed")
                if fixed:
                    out.append(str(fixed))
    return sorted(set(out))


def _summarize(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "aliases": record.get("aliases") or [],  # usually the CVE id
        "summary": record.get("summary") or "",
        "details": (record.get("details") or "")[:600],
        "severity": _severity_label(record),
        "cvss": [s.get("score") for s in (record.get("severity") or []) if s.get("score")],
        "fixed": _fixed_versions(record),
        "url": f"https://osv.dev/vulnerability/{record.get('id')}",
    }


async def osv_scan(
    packages: list[dict[str, Any]],
    *,
    ecosystem: str = "PyPI",
) -> dict[str, Any]:
    """Scan a dependency list against OSV.dev.

    `packages` is a list of {"name": str, "version"?: str, "ecosystem"?: str}.
    A query with no version returns every vulnerability known for that
    package, which is still a useful signal when only a constraint is known.
    """
    if not packages or not isinstance(packages, list):
        raise ValueError("packages must be a non-empty list")

    queries: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for p in packages:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        eco = str(p.get("ecosystem") or ecosystem).strip() or ecosystem
        version = p.get("version")
        q: dict[str, Any] = {"package": {"name": name, "ecosystem": eco}}
        if version:
            q["version"] = str(version)
        queries.append(q)
        index.append({"name": name, "version": version, "ecosystem": eco})

    if not queries:
        raise ValueError("no valid packages to scan")

    async with httpx.AsyncClient(timeout=30.0, trust_env=False, proxy=_WEB_PROXY) as client:
        r = await client.post(_QUERYBATCH, json={"queries": queries})
        r.raise_for_status()
        batch = r.json()

        results = batch.get("results") or []
        # Collect unique vuln ids while remembering which package hit them.
        per_package: list[dict[str, Any]] = []
        ids: list[str] = []
        for pkg, res in zip(index, results):
            hits = [v.get("id") for v in (res.get("vulns") or []) if v.get("id")]
            per_package.append({**pkg, "vuln_ids": hits})
            for vid in hits:
                if vid not in ids:
                    ids.append(vid)

        # Hydrate full records for the detail view (bounded).
        detail_ids = ids[:_MAX_DETAIL]
        records = await asyncio.gather(
            *(_fetch_vuln(client, vid) for vid in detail_ids),
            return_exceptions=True,
        )

    findings: list[dict[str, Any]] = []
    for rec in records:
        if isinstance(rec, dict):
            findings.append(_summarize(rec))
        elif isinstance(rec, Exception):
            log.warning("osv vuln fetch failed: %s", rec)

    return {
        "ecosystem": ecosystem,
        "packages_scanned": len(queries),
        "vulnerable_packages": sum(1 for p in per_package if p["vuln_ids"]),
        "total_vulnerabilities": len(ids),
        "per_package": per_package,
        "findings": findings,
        "truncated": len(ids) > _MAX_DETAIL,
    }


async def _fetch_vuln(client: httpx.AsyncClient, vuln_id: str) -> dict[str, Any]:
    r = await client.get(_VULN + vuln_id)
    r.raise_for_status()
    return r.json()
