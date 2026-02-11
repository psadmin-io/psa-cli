"""PeopleSoft psadmin command executor."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from psa.core.config import PsaConfig, get_config


@dataclass
class PsadminResult:
    """Result of a psadmin command execution."""

    success: bool
    exit_code: int
    output: str
    command: str

    def __bool__(self) -> bool:
        return self.success


class PsadminExecutor:
    """Execute psadmin commands with proper user context."""

    def __init__(self, config: Optional[PsaConfig] = None):
        self.config = config or get_config()

    def _get_ps_home(self) -> Path:
        """Get PS_HOME path."""
        if self.config.ps_home:
            return self.config.ps_home
        # Try environment
        if ps_home := os.environ.get("PS_HOME"):
            return Path(ps_home)
        # Default location
        return self.config.ps_base / "pt"

    def _get_psadmin_path(self) -> str:
        """Get path to psadmin executable."""
        return str(self._get_ps_home() / "bin" / "psadmin")

    def _is_runtime_user(self) -> bool:
        """Check if current user is the domain runtime user."""
        return os.environ.get("USER") == self.config.runtime_user

    def _build_command(
        self,
        args: list[str],
        ps_cfg_home: Optional[Path] = None,
    ) -> list[str]:
        """Build the full command with sudo if needed."""
        psadmin = self._get_psadmin_path()
        base_cmd = [psadmin] + args

        # Set PS_CFG_HOME if specified
        env_prefix = ""
        if ps_cfg_home:
            env_prefix = f"PS_CFG_HOME={ps_cfg_home} "

        if self._is_runtime_user() or not self.config.sudo_enabled:
            # Run directly
            if env_prefix:
                return ["sh", "-c", f"{env_prefix}{' '.join(base_cmd)}"]
            return base_cmd
        else:
            # Run with sudo as runtime_user
            cmd_str = f"{env_prefix}{' '.join(base_cmd)}"
            return ["sudo", "su", "-", self.config.runtime_user, "-c", cmd_str]

    def run(
        self,
        args: list[str],
        ps_cfg_home: Optional[Path] = None,
        timeout: int = 300,
    ) -> PsadminResult:
        """Run a psadmin command.

        Args:
            args: Arguments to pass to psadmin (e.g., ["-c", "sstatus", "-d", "APPDOM"])
            ps_cfg_home: Optional PS_CFG_HOME override
            timeout: Command timeout in seconds

        Returns:
            PsadminResult with success status, exit code, and output
        """
        cmd = self._build_command(args, ps_cfg_home)
        cmd_str = " ".join(cmd)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return PsadminResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                output=result.stdout + result.stderr,
                command=cmd_str,
            )
        except subprocess.TimeoutExpired:
            return PsadminResult(
                success=False,
                exit_code=-1,
                output=f"Command timed out after {timeout} seconds",
                command=cmd_str,
            )
        except FileNotFoundError:
            return PsadminResult(
                success=False,
                exit_code=-1,
                output=f"psadmin not found at {self._get_psadmin_path()}",
                command=cmd_str,
            )
        except Exception as e:
            return PsadminResult(
                success=False,
                exit_code=-1,
                output=str(e),
                command=cmd_str,
            )

    # Appserver domain commands
    def app_status(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Get appserver domain status."""
        results = []
        for args in [
            ["-c", "sstatus", "-d", domain],
            ["-c", "cstatus", "-d", domain],
            ["-c", "qstatus", "-d", domain],
        ]:
            results.append(self.run(args, ps_cfg_home))

        # Combine outputs
        combined_output = "\n".join(r.output for r in results)
        all_success = all(r.success for r in results)
        return PsadminResult(
            success=all_success,
            exit_code=0 if all_success else 1,
            output=combined_output,
            command="psadmin status",
        )

    def app_start(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Start appserver domain."""
        if self.config.parallel_boot:
            return self.run(["-c", "parallelboot", "-d", domain], ps_cfg_home)
        return self.run(["-c", "boot", "-d", domain], ps_cfg_home)

    def app_stop(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Stop appserver domain."""
        return self.run(["-c", "shutdown", "-d", domain], ps_cfg_home)

    def app_kill(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Force stop appserver domain."""
        return self.run(["-c", "shutdown!", "-d", domain], ps_cfg_home)

    def app_configure(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Configure appserver domain."""
        return self.run(["-c", "configure", "-d", domain], ps_cfg_home)

    def app_purge(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Purge appserver domain cache."""
        return self.run(["-c", "purge", "-d", domain], ps_cfg_home)

    def app_flush(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Flush appserver domain IPC."""
        return self.run(["-c", "cleanipc", "-d", domain], ps_cfg_home)

    # Process scheduler domain commands
    def prcs_status(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Get process scheduler domain status."""
        return self.run(["-p", "status", "-d", domain], ps_cfg_home)

    def prcs_start(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Start process scheduler domain."""
        return self.run(["-p", "start", "-d", domain], ps_cfg_home)

    def prcs_stop(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Stop process scheduler domain."""
        return self.run(["-p", "stop", "-d", domain], ps_cfg_home)

    def prcs_kill(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Force stop process scheduler domain."""
        return self.run(["-p", "kill", "-d", domain], ps_cfg_home)

    def prcs_configure(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Configure process scheduler domain."""
        return self.run(["-p", "configure", "-d", domain], ps_cfg_home)

    def prcs_flush(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Flush process scheduler domain IPC."""
        return self.run(["-p", "cleanipc", "-d", domain], ps_cfg_home)

    def prcs_purge(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Purge process scheduler domain cache."""
        # PRCS cache is cleared manually
        cache_path = ps_cfg_home or self.config.get_ps_cfg_home()
        cache_dir = cache_path / "appserv" / "prcs" / domain / "CACHE"
        try:
            if cache_dir.exists():
                import shutil
                for item in cache_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            return PsadminResult(
                success=True,
                exit_code=0,
                output=f"Purged cache: {cache_dir}",
                command=f"rm -rf {cache_dir}/*",
            )
        except Exception as e:
            return PsadminResult(
                success=False,
                exit_code=1,
                output=str(e),
                command=f"rm -rf {cache_dir}/*",
            )

    # Web server domain commands
    def web_status(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Get web server domain status."""
        return self.run(["-w", "status", "-d", domain], ps_cfg_home)

    def web_start(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Start web server domain."""
        # Use startPIA.sh script
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        script = cfg_home / "webserv" / domain / "bin" / "startPIA.sh"
        return self._run_web_script(script, domain)

    def web_stop(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Stop web server domain."""
        # Use stopPIA.sh script
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        script = cfg_home / "webserv" / domain / "bin" / "stopPIA.sh"
        return self._run_web_script(script, domain)

    def web_kill(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Force stop web server domain."""
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        # Kill java process for this domain
        cmd = f"pkill -f '{cfg_home}/webserv/{domain}/piaconfig'"
        try:
            result = subprocess.run(
                ["sh", "-c", cmd],
                capture_output=True,
                text=True,
            )
            return PsadminResult(
                success=True,  # pkill returns non-zero if no process found
                exit_code=result.returncode,
                output=result.stdout + result.stderr or "Killed web processes",
                command=cmd,
            )
        except Exception as e:
            return PsadminResult(
                success=False,
                exit_code=1,
                output=str(e),
                command=cmd,
            )

    def web_purge(self, domain: str, ps_cfg_home: Optional[Path] = None) -> PsadminResult:
        """Purge web server domain cache."""
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        cache_pattern = cfg_home / "webserv" / domain / "applications" / "peoplesoft" / "PORTAL*" / "*" / "cache*"
        try:
            import glob
            import shutil
            cache_dirs = glob.glob(str(cache_pattern))
            for cache_dir in cache_dirs:
                shutil.rmtree(cache_dir, ignore_errors=True)
            return PsadminResult(
                success=True,
                exit_code=0,
                output=f"Purged {len(cache_dirs)} cache directories",
                command=f"rm -rf {cache_pattern}",
            )
        except Exception as e:
            return PsadminResult(
                success=False,
                exit_code=1,
                output=str(e),
                command=f"rm -rf {cache_pattern}",
            )

    def _run_web_script(self, script: Path, domain: str) -> PsadminResult:
        """Run a web server script (startPIA.sh or stopPIA.sh)."""
        if not script.exists():
            return PsadminResult(
                success=False,
                exit_code=1,
                output=f"Script not found: {script}",
                command=str(script),
            )

        cmd = [str(script)]
        if not self._is_runtime_user() and self.config.sudo_enabled:
            cmd = ["sudo", "su", "-", self.config.runtime_user, "-c", str(script)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return PsadminResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                output=result.stdout + result.stderr,
                command=" ".join(cmd),
            )
        except Exception as e:
            return PsadminResult(
                success=False,
                exit_code=1,
                output=str(e),
                command=" ".join(cmd),
            )
