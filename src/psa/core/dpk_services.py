"""DPK-installed systemd unit management for domain services.

The DPK installs per-domain systemd units named ``psft-{appserver,prcs,pia}-<DOMAIN>``.
Their unit files (or symlinks) land in one of:

  - ``/etc/systemd/system/<unit>.service``
  - ``/usr/lib/systemd/system/<unit>.service``
  - ``/etc/systemd/system/multi-user.target.wants/<unit>.service``

Removal sequence per unit: stop -> disable -> rm. A single ``systemctl daemon-reload``
is the caller's responsibility (run once after all units are removed).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_PREFIX = {
    "app": "psft-appserver",
    "prcs": "psft-prcs",
    "web": "psft-pia",
}

UNIT_SEARCH_DIRS = [
    Path("/etc/systemd/system"),
    Path("/usr/lib/systemd/system"),
    Path("/etc/systemd/system/multi-user.target.wants"),
]


@dataclass
class ServiceOpResult:
    """Outcome of a service teardown step."""

    success: bool
    output: str
    removed_paths: list[Path] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.success


def unit_name(domain_type: str, domain_name: str) -> str:
    """Return systemd unit name for a domain (without ``.service`` suffix)."""
    prefix = SERVICE_PREFIX.get(domain_type)
    if not prefix:
        raise ValueError(f"Unknown domain type: {domain_type}")
    return f"{prefix}-{domain_name}"


def find_unit_paths(unit: str) -> list[Path]:
    """Return all existing paths (file or symlink) for a unit name.

    ``unit`` may be supplied with or without the ``.service`` suffix.
    """
    if not unit.endswith(".service"):
        unit = f"{unit}.service"
    found: list[Path] = []
    for d in UNIT_SEARCH_DIRS:
        candidate = d / unit
        # is_symlink works even when the symlink target is missing
        if candidate.is_symlink() or candidate.exists():
            found.append(candidate)
    return found


def _wrap_sudo(cmd: list[str]) -> list[str]:
    """Prepend sudo when not already root."""
    if os.geteuid() == 0:
        return cmd
    return ["sudo"] + cmd


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def remove_unit(
    domain_type: str,
    domain_name: str,
    dry_run: bool = False,
) -> ServiceOpResult:
    """Stop, disable, and remove the DPK systemd unit for one domain.

    Idempotent: missing units yield success with an empty ``removed_paths``.
    Best-effort: ``stop``/``disable`` failures (already-stopped, not-enabled)
    are not treated as errors. ``rm`` failure is fatal.

    Returns aggregated log via ``output``. Caller is responsible for invoking
    ``systemctl daemon-reload`` once after all removals.
    """
    try:
        uname = unit_name(domain_type, domain_name)
    except ValueError as e:
        return ServiceOpResult(success=False, output=str(e))

    paths = find_unit_paths(uname)
    log: list[str] = []

    if not paths:
        return ServiceOpResult(
            success=True,
            output=f"No DPK service unit found for {uname}",
        )

    if dry_run:
        log.append(f"[dry-run] would remove unit {uname}:")
        for p in paths:
            log.append(f"  rm {p}")
        return ServiceOpResult(success=True, output="\n".join(log), removed_paths=paths)

    # Stop (best-effort)
    stop_cmd = _wrap_sudo(["systemctl", "stop", f"{uname}.service"])
    r = _run(stop_cmd)
    if r.returncode != 0:
        log.append(f"systemctl stop {uname}: rc={r.returncode} {r.stderr.strip()}")

    # Disable (best-effort; also removes the multi-user.target.wants symlink)
    disable_cmd = _wrap_sudo(["systemctl", "disable", f"{uname}.service"])
    r = _run(disable_cmd)
    if r.returncode != 0:
        log.append(f"systemctl disable {uname}: rc={r.returncode} {r.stderr.strip()}")

    # rm any unit files that remain (disable may have already cleared the
    # target.wants symlink, so re-scan)
    remaining = find_unit_paths(uname)
    removed: list[Path] = []
    rm_failed = False
    for p in remaining:
        rm_cmd = _wrap_sudo(["rm", "-f", str(p)])
        r = _run(rm_cmd)
        if r.returncode != 0:
            log.append(f"rm {p}: rc={r.returncode} {r.stderr.strip()}")
            rm_failed = True
        else:
            removed.append(p)

    success = not rm_failed
    if success and not log:
        log.append(f"Removed unit {uname} ({len(removed)} path(s))")
    return ServiceOpResult(success=success, output="\n".join(log), removed_paths=removed)


def daemon_reload(dry_run: bool = False) -> ServiceOpResult:
    """Run ``systemctl daemon-reload``. Call once after batch removals."""
    if dry_run:
        return ServiceOpResult(success=True, output="[dry-run] systemctl daemon-reload")
    cmd = _wrap_sudo(["systemctl", "daemon-reload"])
    r = _run(cmd)
    return ServiceOpResult(
        success=r.returncode == 0,
        output=(r.stdout + r.stderr).strip() or "daemon-reload ok",
    )
