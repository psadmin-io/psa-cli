"""PeopleSoft environment detection utilities."""

from __future__ import annotations

import os
import pwd
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PsEnvironment:
    """Detected PeopleSoft environment information."""

    ps_home: Optional[Path] = None
    ps_cfg_home: Optional[Path] = None
    ps_app_home: Optional[Path] = None
    ps_cust_home: Optional[Path] = None
    tuxdir: Optional[Path] = None
    oracle_home: Optional[Path] = None
    weblogic_home: Optional[Path] = None
    java_home: Optional[Path] = None
    current_user: str = ""
    is_ps_user: bool = False

    @classmethod
    def detect(cls) -> "PsEnvironment":
        """Detect PeopleSoft environment from current context."""
        env = cls()

        # Get current user
        env.current_user = pwd.getpwuid(os.getuid()).pw_name
        env.is_ps_user = env.current_user in ("psadm1", "psadm2", "psadm3")

        # Check environment variables first
        env.ps_home = _path_from_env("PS_HOME")
        env.ps_cfg_home = _path_from_env("PS_CFG_HOME")
        env.ps_app_home = _path_from_env("PS_APP_HOME")
        env.ps_cust_home = _path_from_env("PS_CUST_HOME")
        env.tuxdir = _path_from_env("TUXDIR")
        env.oracle_home = _path_from_env("ORACLE_HOME")
        env.java_home = _path_from_env("JAVA_HOME")

        # Try to detect from common paths if not in environment
        if not env.ps_cfg_home:
            env.ps_cfg_home = _find_ps_cfg_home()

        if not env.ps_home and env.ps_cfg_home:
            env.ps_home = _find_ps_home_from_cfg(env.ps_cfg_home)

        return env


def _path_from_env(var: str) -> Optional[Path]:
    """Get a Path from an environment variable if set and exists."""
    if value := os.environ.get(var):
        path = Path(value)
        if path.exists():
            return path
    return None


def _find_ps_cfg_home() -> Optional[Path]:
    """Try to find PS_CFG_HOME from common locations."""
    common_paths = [
        Path("/u01/app/psoft/cfg"),
        Path("/opt/oracle/psft/cfg"),
        Path("/home/psadm2/psft/cfg"),
    ]

    for path in common_paths:
        if path.exists() and path.is_dir():
            # Verify it looks like a PS_CFG_HOME
            if (path / "appserv").exists() or (path / "webserv").exists():
                return path

    return None


def _find_ps_home_from_cfg(ps_cfg_home: Path) -> Optional[Path]:
    """Try to find PS_HOME based on PS_CFG_HOME location."""
    # Often PS_HOME is a sibling directory
    parent = ps_cfg_home.parent

    # Check for pt directory (PeopleTools)
    pt_path = parent / "pt"
    if pt_path.exists():
        # Find the latest tools version
        tools_dirs = sorted(pt_path.glob("ps_home*"), reverse=True)
        if tools_dirs:
            return tools_dirs[0]

    return None


def run_psadmin(args: list[str], domain: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run psadmin command with given arguments."""
    cmd = ["psadmin"] + args
    if domain:
        cmd.extend(["-d", domain])

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def get_psadmin_path() -> Optional[Path]:
    """Find the psadmin executable."""
    # Check PATH first
    result = subprocess.run(
        ["which", "psadmin"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())

    # Check PS_HOME
    if ps_home := os.environ.get("PS_HOME"):
        psadmin = Path(ps_home) / "bin" / "psadmin"
        if psadmin.exists():
            return psadmin

    return None
