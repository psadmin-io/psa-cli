"""Local cache for domain name → UUID mappings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CACHE_PATH = Path.home() / ".config" / "psa" / "domains.json"


def load_cache(cache_path: Optional[Path] = None) -> dict:
    """Load the domain cache. Returns {name: {id, node_id, type}} mapping."""
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

    The ingest endpoint returns a ``domains`` list with ``id``, ``name``,
    ``domain_type`` etc.  We merge these into the existing cache keyed by
    domain name.
    """
    cache = load_cache(cache_path)
    for domain in ingest_result.get("domains", []):
        name = domain.get("name")
        domain_id = domain.get("id")
        if name and domain_id:
            cache[name] = {
                "id": domain_id,
                "node_id": domain.get("node_id"),
                "type": domain.get("domain_type"),
            }
    save_cache(cache, cache_path)
    return cache


def get_cached_domain_id(name: str, cache_path: Optional[Path] = None) -> Optional[str]:
    """Look up a cached domain UUID by name. Returns None on cache miss."""
    cache = load_cache(cache_path)
    entry = cache.get(name)
    if entry:
        return entry.get("id")
    return None
