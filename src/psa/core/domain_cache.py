"""Local cache for domain name → UUID mappings.

Domains can share names across types (e.g. IHDEV/app + IHDEV/prcs), so the
cache uses composite keys ``"<name>:<type>"`` for type-aware entries. A
legacy flat ``<name>`` key is still readable for backward-compat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CACHE_PATH = Path.home() / ".config" / "psa" / "domains.json"


def _composite_key(name: str, domain_type: Optional[str]) -> str:
    return f"{name}:{domain_type}" if domain_type else name


def load_cache(cache_path: Optional[Path] = None) -> dict:
    """Load the domain cache."""
    path = cache_path or CACHE_PATH
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict, cache_path: Optional[Path] = None) -> None:
    """Write the domain cache."""
    path = cache_path or CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, indent=2)


def update_cache_from_ingest(ingest_result: dict, cache_path: Optional[Path] = None) -> dict:
    """Update cache from a scan/ingest response.

    Writes a composite ``name:type`` key per domain so same-named domains
    with different types coexist. Also writes a flat ``name`` key when the
    type is unknown so legacy callers still resolve.
    """
    cache = load_cache(cache_path)
    for domain in ingest_result.get("domains", []):
        name = domain.get("name")
        domain_id = domain.get("id")
        if not (name and domain_id):
            continue
        # PSA-OPS canonical field is `type`; accept `domain_type` defensively.
        domain_type = domain.get("type") or domain.get("domain_type")
        entry = {
            "id": domain_id,
            "node_id": domain.get("node_id"),
            "type": domain_type,
        }
        cache[_composite_key(name, domain_type)] = entry
        if not domain_type:
            cache[name] = entry
    save_cache(cache, cache_path)
    return cache


def get_cached_domain_id(
    name: str,
    domain_type: Optional[str] = None,
    cache_path: Optional[Path] = None,
) -> Optional[str]:
    """Look up a cached domain UUID by name (+ optional type).

    Returns None on cache miss or when ``domain_type`` is omitted and
    multiple typed entries exist for the same name (ambiguous).
    """
    cache = load_cache(cache_path)

    if domain_type:
        entry = cache.get(_composite_key(name, domain_type))
        if entry:
            return entry.get("id")
        # Legacy flat entry whose stored type matches
        legacy = cache.get(name)
        if legacy and legacy.get("type") == domain_type:
            return legacy.get("id")
        return None

    # No type filter: prefer the flat key, else fall through to typed entries
    legacy = cache.get(name)
    if legacy:
        return legacy.get("id")
    prefix = f"{name}:"
    matches = [v for k, v in cache.items() if k.startswith(prefix)]
    if len(matches) == 1:
        return matches[0].get("id")
    return None
