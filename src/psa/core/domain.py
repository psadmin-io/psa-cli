"""Domain discovery and parsing utilities."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from psa.core.config import PsaConfig, get_config
from psa.core.fileops import SudoFileOps


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
        self.fileops = SudoFileOps(self.config)

    def _read_config_file(self, config_file: Path) -> Optional[dict[str, Any]]:
        """Read raw config file content if within size limit.

        Returns dict with type, path, content or None if file too large/unreadable.
        """
        size = self.fileops.stat_size(config_file)
        if size is None or size > MAX_CONFIG_FILE_SIZE:
            return None
        content = self.fileops.read_text(config_file)
        if content is None:
            return None
        return {
            "type": config_file.name,
            "path": str(config_file),
            "content": content,
        }

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
        # Scope discovery to requested type when possible
        for cfg_home in self.config.get_all_cfg_homes():
            if domain_type:
                if domain_type == "app":
                    domains = self.discover_appserver_domains(cfg_home)
                elif domain_type == "prcs":
                    domains = self.discover_prcs_domains(cfg_home)
                elif domain_type == "pia":
                    domains = self.discover_pia_domains(cfg_home)
                else:
                    domains = []
            else:
                domains = self.discover_all(cfg_home)
            for domain in domains:
                if domain.name == name:
                    return domain
        return None

    def discover_appserver_domains(self, ps_cfg_home: Optional[Path] = None) -> list[DomainInfo]:
        """Discover application server domains."""
        domains = []
        cfg_home = ps_cfg_home or self.config.get_ps_cfg_home()
        appserv_path = cfg_home / "appserv"

        if not self.fileops.exists(appserv_path):
            return domains

        for name, is_dir in self.fileops.listdir(appserv_path):
            if not is_dir:
                continue

            # Skip special directories
            if name in ("prcs", "search", "piaconfig"):
                continue

            domain_dir = appserv_path / name

            # Check for psappsrv.cfg to confirm it's an appserver domain
            config_file = domain_dir / "psappsrv.cfg"
            if self.fileops.exists(config_file):
                domain = DomainInfo(
                    name=name,
                    domain_type="app",
                    path=domain_dir,
                    ps_cfg_home=cfg_home,
                )
                domain.config = self._parse_appserver_config(config_file)
                domain.status = self._check_appserver_status(domain_dir)
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

        if not self.fileops.exists(prcs_path):
            return domains

        for name, is_dir in self.fileops.listdir(prcs_path):
            if not is_dir:
                continue

            domain_dir = prcs_path / name

            # Check for psprcs.cfg to confirm it's a prcs domain
            config_file = domain_dir / "psprcs.cfg"
            if self.fileops.exists(config_file):
                domain = DomainInfo(
                    name=name,
                    domain_type="prcs",
                    path=domain_dir,
                    ps_cfg_home=cfg_home,
                )
                domain.config = self._parse_prcs_config(config_file)
                domain.status = self._check_prcs_status(domain_dir)
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

        if not self.fileops.exists(webserv_path):
            return domains

        for name, is_dir in self.fileops.listdir(webserv_path):
            if not is_dir:
                continue

            domain_dir = webserv_path / name
            config_xml = domain_dir / "config" / "config.xml"

            # config.xml is the reliable existence indicator
            if not self.fileops.exists(config_xml):
                continue

            domain = DomainInfo(
                name=name,
                domain_type="pia",
                path=domain_dir,
                ps_cfg_home=cfg_home,
            )

            # Find configuration.properties — flat path first, then DPK WAR path
            config_props = None
            flat_path = domain_dir / "applications" / "peoplesoft" / "configuration.properties"
            if self.fileops.exists(flat_path):
                config_props = flat_path
            else:
                psftdocs = domain_dir / "applications" / "peoplesoft" / "PORTAL.war" / "WEB-INF" / "psftdocs"
                if self.fileops.exists(psftdocs):
                    for site_name, site_is_dir in self.fileops.listdir(psftdocs):
                        if site_is_dir:
                            candidate = psftdocs / site_name / "configuration.properties"
                            if self.fileops.exists(candidate):
                                config_props = candidate
                                break

            if config_props:
                domain.config = self._parse_pia_config(config_props)
                raw_config = self._read_config_file(config_props)
                if raw_config:
                    domain.config_files.append(raw_config)

            domain.status = self._check_pia_status(domain_dir)
            domains.append(domain)

        return domains

    def _parse_appserver_config(self, config_file: Path) -> dict[str, Any]:
        """Parse psappsrv.cfg configuration file."""
        config = {}
        content = self.fileops.read_text(config_file)
        if not content:
            return config
        try:
            parser = configparser.ConfigParser()
            parser.read_string(content)

            if parser.has_section("Startup"):
                startup = dict(parser.items("Startup"))
                config["db_name"] = startup.get("dbname", "")
                config["db_type"] = startup.get("dbtype", "")

            if parser.has_section("Domain Settings"):
                domain_settings = dict(parser.items("Domain Settings"))
                config["domain_id"] = domain_settings.get("domain id", "")

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
        content = self.fileops.read_text(config_file)
        if not content:
            return config
        try:
            parser = configparser.ConfigParser()
            parser.read_string(content)

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
        content = self.fileops.read_text(config_file)
        if not content:
            return config
        try:
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

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
        """Check if a prcs domain is running via filesystem."""
        if self.fileops.exists(domain_path / "LOGS" / "TUXLOG"):
            return "unknown"  # can't tell running vs stopped from file alone
        return "stopped"

    def _check_pia_status(self, domain_path: Path) -> str:
        """Check if a PIA domain is running via filesystem."""
        pid_file = domain_path / "servers" / "PIA" / "tmp" / "PIA.pid"
        if self.fileops.exists(pid_file):
            return "unknown"  # PID exists, might be running
        return "stopped"


def discover_domains(config: Optional[PsaConfig] = None) -> list[dict[str, Any]]:
    """Discover all domains and return as list of dicts."""
    discovery = DomainDiscovery(config)
    domains = discovery.discover_all()
    return [d.to_dict() for d in domains]
