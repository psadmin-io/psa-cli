"""Domain discovery and parsing utilities."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from psa.core.config import PsaConfig, get_config


MAX_CONFIG_FILE_SIZE = 100 * 1024  # 100KB limit for raw config capture


@dataclass
class DomainInfo:
    """Information about a PeopleSoft domain."""

    name: str
    domain_type: str  # app, prcs, pia
    path: Path
    ps_cfg_home: Optional[Path] = None  # PS_CFG_HOME this domain belongs to
    status: str = "unknown"
    config: dict = field(default_factory=dict)
    config_files: list = field(default_factory=list)  # raw config file contents

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "name": self.name,
            "type": self.domain_type,
            "path": str(self.path),
            "ps_cfg_home": str(self.ps_cfg_home) if self.ps_cfg_home else None,
            "status": self.status,
            "config": self.config,
            "config_files": self.config_files,
        }


class DomainDiscovery:
    """Discover PeopleSoft domains on the system."""

    def __init__(self, config: Optional[PsaConfig] = None):
        self.config = config or get_config()

    def _read_config_file(self, config_file: Path) -> Optional[dict[str, Any]]:
        """Read raw config file content if within size limit.

        Returns dict with type, path, content or None if file too large/unreadable.
        """
        try:
            size = config_file.stat().st_size
            if size > MAX_CONFIG_FILE_SIZE:
                return None
            content = config_file.read_text(encoding="utf-8", errors="replace")
            return {
                "type": config_file.name,
                "path": str(config_file),
                "content": content,
            }
        except Exception:
            return None

    def discover_all(self, ps_cfg_home: Optional[Path] = None) -> list[DomainInfo]:
        """Discover all domain types in a single PS_CFG_HOME."""
        domains = []
        domains.extend(self.discover_appserver_domains(ps_cfg_home))
        domains.extend(self.discover_prcs_domains(ps_cfg_home))
        domains.extend(self.discover_pia_domains(ps_cfg_home))
        return domains

    def discover_all_homes(self) -> list[DomainInfo]:
        """Discover domains across all PS_CFG_HOME paths (primary + multi_homes)."""
        domains = []
        for cfg_home in self.config.get_all_cfg_homes():
            domains.extend(self.discover_all(cfg_home))
        return domains

    def find_domain(
        self,
        name: str,
        domain_type: Optional[str] = None,
    ) -> Optional[DomainInfo]:
        """Find a domain by name, optionally filtering by type.

        Args:
            name: Domain name to find
            domain_type: Optional type filter (app, prcs, pia)

        Returns:
            DomainInfo if found, None otherwise
        """
        domains = self.discover_all_homes()
        for domain in domains:
            if domain.name == name:
                if domain_type is None or domain.domain_type == domain_type:
                    return domain
        return None

    def discover_appserver_domains(self, ps_cfg_home: Optional[Path] = None) -> list[DomainInfo]:
        """Discover application server domains."""
        domains = []
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        appserv_path = cfg_home / "appserv"

        if not appserv_path.exists():
            return domains

        for domain_dir in appserv_path.iterdir():
            if not domain_dir.is_dir():
                continue

            # Skip special directories
            if domain_dir.name in ("prcs", "search", "piaconfig"):
                continue

            # Check for psappsrv.cfg to confirm it's an appserver domain
            config_file = domain_dir / "psappsrv.cfg"
            if config_file.exists():
                domain = DomainInfo(
                    name=domain_dir.name,
                    domain_type="app",
                    path=domain_dir,
                    ps_cfg_home=cfg_home,
                )
                domain.config = self._parse_appserver_config(config_file)
                domain.status = self._check_appserver_status(domain_dir)
                # Capture raw config file content
                raw_config = self._read_config_file(config_file)
                if raw_config:
                    domain.config_files.append(raw_config)
                domains.append(domain)

        return domains

    def discover_prcs_domains(self, ps_cfg_home: Optional[Path] = None) -> list[DomainInfo]:
        """Discover process scheduler domains."""
        domains = []
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        prcs_path = cfg_home / "appserv" / "prcs"

        if not prcs_path.exists():
            return domains

        for domain_dir in prcs_path.iterdir():
            if not domain_dir.is_dir():
                continue

            # Check for psprcs.cfg to confirm it's a prcs domain
            config_file = domain_dir / "psprcs.cfg"
            if config_file.exists():
                domain = DomainInfo(
                    name=domain_dir.name,
                    domain_type="prcs",
                    path=domain_dir,
                    ps_cfg_home=cfg_home,
                )
                domain.config = self._parse_prcs_config(config_file)
                domain.status = self._check_prcs_status(domain_dir)
                # Capture raw config file content
                raw_config = self._read_config_file(config_file)
                if raw_config:
                    domain.config_files.append(raw_config)
                domains.append(domain)

        return domains

    def discover_pia_domains(self, ps_cfg_home: Optional[Path] = None) -> list[DomainInfo]:
        """Discover PIA (web server) domains."""
        domains = []
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        webserv_path = cfg_home / "webserv"

        if not webserv_path.exists():
            return domains

        for domain_dir in webserv_path.iterdir():
            if not domain_dir.is_dir():
                continue

            # Check for configuration.properties or config.xml
            config_props = domain_dir / "applications" / "peoplesoft" / "configuration.properties"
            config_xml = domain_dir / "config" / "config.xml"

            if config_props.exists() or config_xml.exists():
                domain = DomainInfo(
                    name=domain_dir.name,
                    domain_type="pia",
                    path=domain_dir,
                    ps_cfg_home=cfg_home,
                )
                if config_props.exists():
                    domain.config = self._parse_pia_config(config_props)
                    # Capture raw config file content
                    raw_config = self._read_config_file(config_props)
                    if raw_config:
                        domain.config_files.append(raw_config)
                domain.status = self._check_pia_status(domain_dir)
                domains.append(domain)

        return domains

    def _parse_appserver_config(self, config_file: Path) -> dict[str, Any]:
        """Parse psappsrv.cfg configuration file."""
        config = {}
        try:
            parser = configparser.ConfigParser()
            parser.read(config_file)

            # Extract key settings from Startup section
            if parser.has_section("Startup"):
                startup = dict(parser.items("Startup"))
                config["db_name"] = startup.get("dbname", "")
                config["db_type"] = startup.get("dbtype", "")

            # Extract from Domain Settings
            if parser.has_section("Domain Settings"):
                domain_settings = dict(parser.items("Domain Settings"))
                config["domain_id"] = domain_settings.get("domain id", "")

            # Extract JOLT listener info
            if parser.has_section("JOLT Listener"):
                jolt = dict(parser.items("JOLT Listener"))
                config["jolt_port"] = jolt.get("port", "")
                config["jolt_address"] = jolt.get("address", "")

        except Exception:
            pass

        return config

    def _parse_prcs_config(self, config_file: Path) -> dict[str, Any]:
        """Parse psprcs.cfg configuration file."""
        config = {}
        try:
            parser = configparser.ConfigParser()
            parser.read(config_file)

            if parser.has_section("Startup"):
                startup = dict(parser.items("Startup"))
                config["db_name"] = startup.get("dbname", "")
                config["db_type"] = startup.get("dbtype", "")
                config["prcs_server_name"] = startup.get("prcsservername", "")

        except Exception:
            pass

        return config

    def _parse_pia_config(self, config_file: Path) -> dict[str, Any]:
        """Parse PIA configuration.properties file."""
        config = {}
        try:
            # configuration.properties is a Java properties file
            with open(config_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()

                        # Extract key properties
                        if key == "psserver":
                            config["app_server"] = value
                        elif key == "psport":
                            config["jolt_port"] = value
                        elif key == "webprofile":
                            config["web_profile"] = value

        except Exception:
            pass

        return config

    def _check_appserver_status(self, domain_path: Path) -> str:
        """Check if an appserver domain is running."""
        # Look for PSTUX.lock or running processes
        lock_file = domain_path / "LOGS" / "TUXLOG"
        if lock_file.exists():
            # Could check for actual running processes here
            return "unknown"
        return "stopped"

    def _check_prcs_status(self, domain_path: Path) -> str:
        """Check if a prcs domain is running."""
        return "unknown"

    def _check_pia_status(self, domain_path: Path) -> str:
        """Check if a PIA domain is running."""
        # Check for WebLogic server running
        return "unknown"


def discover_domains(config: Optional[PsaConfig] = None) -> list[dict[str, Any]]:
    """Discover all domains and return as list of dicts."""
    discovery = DomainDiscovery(config)
    domains = discovery.discover_all()
    return [d.to_dict() for d in domains]
