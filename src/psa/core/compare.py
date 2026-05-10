"""Config comparison utilities for local and API-stored configs."""

from __future__ import annotations

import configparser
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from psa.core.fileops import SudoFileOps


@dataclass
class Change:
    """Single key-level diff entry."""

    key: str
    old_value: Optional[str]
    new_value: Optional[str]
    change_type: str  # added, removed, modified


@dataclass
class CompareResult:
    """Result of comparing two config snapshots."""

    has_drift: bool
    changes: List[Change]
    left_label: str
    right_label: str


@dataclass
class ArchiveFile:
    """A timestamped backup in the Archive directory."""

    path: Path
    name: str
    timestamp: str  # raw MMDDYY_HHMM_SS string
    parsed_dt: Optional[datetime] = None


# Primary config file for each domain type
PRIMARY_CONFIGS = {
    "app": "psappsrv.cfg",
    "prcs": "psprcs.cfg",
    "web": "configuration.properties",
}


def get_primary_config(domain_type: str) -> str:
    """Map domain type to its primary config filename."""
    return PRIMARY_CONFIGS.get(domain_type, "psappsrv.cfg")


def format_age(dt: datetime, now: Optional[datetime] = None) -> str:
    """Return human-friendly age string like '3h ago' or '7d ago'."""
    if now is None:
        now = datetime.now()
    delta = now - dt
    total_minutes = int(delta.total_seconds()) // 60
    if total_minutes < 60:
        return f"{max(total_minutes, 0)}m ago"
    total_hours = total_minutes // 60
    if total_hours < 24:
        return f"{total_hours}h ago"
    total_days = total_hours // 24
    return f"{total_days}d ago"


def list_archive_backups(
    fileops: SudoFileOps,
    archive_path: Path,
    config_name: str,
) -> List[ArchiveFile]:
    """List timestamped backups in Archive dir, sorted newest-first.

    Matches pattern: {base}_{MMDDYY}_{HHMM}_{SS}.{ext}
    e.g. psappsrv_012526_1430_22.cfg
    """
    if not fileops.exists(archive_path):
        return []

    base, ext = _split_config_name(config_name)
    # Pattern: base_MMDDYY_HHMM_SS.ext
    pattern = re.compile(
        rf"^{re.escape(base)}_(\d{{6}})_(\d{{4}})_(\d{{2}})\.{re.escape(ext)}$"
    )

    results = []
    for name, is_dir in fileops.listdir(archive_path):
        if is_dir:
            continue
        m = pattern.match(name)
        if m:
            mmddyy, hhmm, ss = m.group(1), m.group(2), m.group(3)
            try:
                parsed_dt = datetime.strptime(
                    f"{mmddyy}{hhmm}{ss}", "%m%d%y%H%M%S"
                )
            except ValueError:
                parsed_dt = None
            results.append(ArchiveFile(
                path=archive_path / name,
                name=name,
                timestamp=f"{mmddyy}_{hhmm}_{ss}",
                parsed_dt=parsed_dt,
            ))

    # Sort newest-first: convert MMDDYY → YYMMDD for chronological ordering
    def sort_key(af: ArchiveFile) -> str:
        mmddyy = af.timestamp[:6]
        yymmdd = mmddyy[4:6] + mmddyy[0:2] + mmddyy[2:4]
        return yymmdd + af.timestamp[6:]

    results.sort(key=sort_key, reverse=True)
    return results


def _split_config_name(config_name: str) -> tuple:
    """Split 'psappsrv.cfg' into ('psappsrv', 'cfg')."""
    dot = config_name.rfind(".")
    if dot == -1:
        return config_name, ""
    return config_name[:dot], config_name[dot + 1:]


def parse_config_to_flat(content: str, config_type: str) -> Dict[str, Optional[str]]:
    """Parse config file content to flat key-value dict.

    INI files (psappsrv.cfg, psprcs.cfg) → Section.Key format.
    Properties files (configuration.properties) → flat key format.

    Matches API's extract_properties() output format.
    """
    if config_type == "configuration.properties":
        return _parse_properties(content)
    return _parse_ini(content)


def _parse_ini(content: str) -> Dict[str, Optional[str]]:
    """Parse INI content to Section.Key flat dict, preserving case."""
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # preserve case
    parser.read_string(content)

    result = {}
    for section in parser.sections():
        for key, val in parser.items(section):
            result[f"{section}.{key}"] = val
    return result


def _parse_properties(content: str) -> Dict[str, Optional[str]]:
    """Parse Java-style properties content to flat dict."""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def extract_api_properties(
    parsed_content: Dict[str, Any],
    config_type: str,
) -> Dict[str, Optional[str]]:
    """Flatten API parsed_content JSONB to same format as parse_config_to_flat.

    Mirrors API's extract_properties() in crud.py.
    """
    props = {}
    sections = parsed_content.get("sections", {})

    if config_type == "configuration.properties":
        for key, val in sections.get("properties", {}).items():
            props[key] = str(val) if val is not None else None
    else:
        for section_name, section_vals in sections.items():
            if isinstance(section_vals, dict):
                for key, val in section_vals.items():
                    props[f"{section_name}.{key}"] = str(val) if val is not None else None

    return props


def diff_configs(
    left: Dict[str, Optional[str]],
    right: Dict[str, Optional[str]],
) -> List[Change]:
    """Compute key-level diff between two flat config dicts.

    left = old/previous, right = current.
    """
    changes = []
    all_keys = sorted(set(left.keys()) | set(right.keys()))

    for key in all_keys:
        in_left = key in left
        in_right = key in right

        if in_left and not in_right:
            changes.append(Change(key, left[key], None, "removed"))
        elif not in_left and in_right:
            changes.append(Change(key, None, right[key], "added"))
        elif left[key] != right[key]:
            changes.append(Change(key, left[key], right[key], "modified"))

    return changes


def resolve_web_config_path(
    fileops: SudoFileOps,
    domain_path: Path,
) -> Optional[Path]:
    """Find configuration.properties for a web (PIA) domain.

    Checks flat path first, then DPK WAR path — same logic as DomainDiscovery.
    """
    flat_path = domain_path / "applications" / "peoplesoft" / "configuration.properties"
    if fileops.exists(flat_path):
        return flat_path

    psftdocs = domain_path / "applications" / "peoplesoft" / "PORTAL.war" / "WEB-INF" / "psftdocs"
    if fileops.exists(psftdocs):
        for site_name, site_is_dir in fileops.listdir(psftdocs):
            if site_is_dir:
                candidate = psftdocs / site_name / "configuration.properties"
                if fileops.exists(candidate):
                    return candidate

    return None
