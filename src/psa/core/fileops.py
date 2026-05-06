"""Filesystem operations with optional sudo elevation."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Optional

from psa.core.config import PsaConfig


class SudoFileOps:
    """Filesystem ops that go through sudo when running as non-runtime user.

    When sudo is needed, delegates to shell commands via
    ``sudo su - <runtime_user> -c "..."``. Otherwise, uses pathlib directly.
    """

    def __init__(self, config: PsaConfig):
        self.config = config

    def _needs_sudo(self) -> bool:
        """Check if sudo is needed for filesystem access."""
        if not self.config.sudo_enabled:
            return False
        return os.environ.get("USER", "") != self.config.runtime_user

    def _run_sudo(self, cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
        """Run a command as the runtime user via sudo."""
        full_cmd = [
            "sudo", "su", "-", self.config.runtime_user, "-c", cmd,
        ]
        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def exists(self, path: Path) -> bool:
        """Check if a path exists."""
        if not self._needs_sudo():
            return path.exists()
        try:
            result = self._run_sudo(f"test -e {path}")
            return result.returncode == 0
        except Exception:
            return False

    def listdir(self, path: Path) -> list[tuple[str, bool]]:
        """List directory contents, returning (name, is_dir) tuples.

        Uses ``ls -1ap`` to batch iterdir + is_dir into one call.
        Directories have trailing ``/`` in ls output.
        """
        if not self._needs_sudo():
            try:
                entries = []
                for child in path.iterdir():
                    entries.append((child.name, child.is_dir()))
                return entries
            except (PermissionError, OSError):
                return []
        try:
            result = self._run_sudo(f"ls -1ap {path}")
            if result.returncode != 0:
                return []
            entries = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line in ("./", "../"):
                    continue
                if line.endswith("/"):
                    entries.append((line.rstrip("/"), True))
                else:
                    entries.append((line, False))
            return entries
        except Exception:
            return []

    def read_text(self, path: Path) -> Optional[str]:
        """Read file contents as text."""
        if not self._needs_sudo():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                return None
        try:
            result = self._run_sudo(f"cat {path}")
            if result.returncode != 0:
                return None
            return result.stdout
        except Exception:
            return None

    def write_text(self, path: Path, content: str, *, as_root: bool = False) -> bool:
        """Write text to a file. Returns True on success.

        Tries a direct write first. If that fails with a permission error, falls
        back to sudo: as `sudo su - <runtime_user>` by default, or as
        `sudo bash -c` when as_root=True (needed for root-owned paths such as
        Puppet's facts.d/). Content is base64-encoded over the wire to avoid
        shell-escaping pitfalls.
        """
        # Try direct write first when we don't already know sudo is required.
        if as_root or not self._needs_sudo():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return True
            except (PermissionError, OSError):
                if not as_root and not self._needs_sudo():
                    # No elevation requested and direct failed — give up.
                    return False
                # Fall through to sudo path

        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        inner = f"mkdir -p {path.parent} && echo {b64} | base64 -d > {path}"

        if as_root:
            full_cmd = ["sudo", "bash", "-c", inner]
        else:
            full_cmd = ["sudo", "su", "-", self.config.runtime_user, "-c", inner]

        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False

    def stat_size(self, path: Path) -> Optional[int]:
        """Get file size in bytes."""
        if not self._needs_sudo():
            try:
                return path.stat().st_size
            except (PermissionError, OSError):
                return None
        try:
            result = self._run_sudo(f"stat -c %s {path}")
            if result.returncode != 0:
                return None
            return int(result.stdout.strip())
        except Exception:
            return None
