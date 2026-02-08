"""Configuration handling for psa tools."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# Default paths for PeopleSoft installations
DEFAULT_PS_BASE = "/u01/app/psoft"
DEFAULT_IO_BASE = "/u01/app/io"

# Config file location
CONFIG_PATH = Path.home() / ".config" / "psa" / "config.yaml"


@dataclass
class HubConfig:
    """Hub connection configuration."""

    url: Optional[str] = None
    node_id: Optional[str] = None
    environment_id: Optional[str] = None
    environment_name: Optional[str] = None
    # Environment-level facts (from environment during init)
    tier: Optional[str] = None
    pillar: Optional[str] = None
    zone: Optional[str] = None
    # Node-level facts (from hub or init)
    ps_role: Optional[str] = None
    # Suppress "using config defaults" warnings
    suppress_fact_warnings: bool = False

    def is_configured(self) -> bool:
        """Check if hub is configured."""
        return self.url is not None


@dataclass
class PsaConfig:
    """Configuration for psa tools."""

    ps_base: Path = field(default_factory=lambda: Path(DEFAULT_PS_BASE))
    io_base: Path = field(default_factory=lambda: Path(DEFAULT_IO_BASE))
    ps_cfg_home: Optional[Path] = None
    ps_home: Optional[Path] = None
    domain_user: str = "psadm2"
    hub: HubConfig = field(default_factory=HubConfig)
    # Domain management settings
    sudo_enabled: bool = True  # Use sudo to run commands as domain_user
    parallel_boot: bool = False  # Use parallelboot instead of boot
    multi_homes: list = field(default_factory=list)  # Additional PS_CFG_HOME paths

    @classmethod
    def from_environment(cls) -> "PsaConfig":
        """Create config from environment variables."""
        config = cls()

        # Override from environment
        if ps_cfg_home := os.environ.get("PS_CFG_HOME"):
            config.ps_cfg_home = Path(ps_cfg_home)

        if ps_home := os.environ.get("PS_HOME"):
            config.ps_home = Path(ps_home)

        if ps_base := os.environ.get("PS_BASE"):
            config.ps_base = Path(ps_base)

        if io_base := os.environ.get("IO_BASE"):
            config.io_base = Path(io_base)

        # Hub from environment
        if hub_url := os.environ.get("PSA_HUB_URL"):
            config.hub.url = hub_url

        if env_id := os.environ.get("PSA_ENVIRONMENT_ID"):
            config.hub.environment_id = env_id

        return config

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "PsaConfig":
        """Load config from YAML file, falling back to environment."""
        path = config_path or CONFIG_PATH

        # Start with environment config
        config = cls.from_environment()

        # Overlay YAML config if exists
        if path.exists():
            try:
                with open(path) as f:
                    data = yaml.safe_load(f) or {}

                # PS paths
                if ps_base := data.get("ps_base"):
                    config.ps_base = Path(ps_base)
                if io_base := data.get("io_base"):
                    config.io_base = Path(io_base)
                if ps_cfg_home := data.get("ps_cfg_home"):
                    config.ps_cfg_home = Path(ps_cfg_home)
                if ps_home := data.get("ps_home"):
                    config.ps_home = Path(ps_home)
                if domain_user := data.get("domain_user"):
                    config.domain_user = domain_user

                # Domain management settings
                if "sudo_enabled" in data:
                    config.sudo_enabled = data["sudo_enabled"]
                if "parallel_boot" in data:
                    config.parallel_boot = data["parallel_boot"]
                if multi_homes := data.get("multi_homes"):
                    config.multi_homes = [Path(p) for p in multi_homes]

                # Hub config (env vars take precedence)
                if hub_data := data.get("hub"):
                    if not config.hub.url:
                        config.hub.url = hub_data.get("url")
                    if not config.hub.node_id:
                        config.hub.node_id = hub_data.get("node_id")
                    if not config.hub.environment_id:
                        config.hub.environment_id = hub_data.get("environment_id")
                    config.hub.environment_name = hub_data.get("environment_name")
                    # Environment-level facts
                    config.hub.tier = hub_data.get("tier")
                    config.hub.pillar = hub_data.get("pillar")
                    config.hub.zone = hub_data.get("zone")
                    # Node-level facts
                    config.hub.ps_role = hub_data.get("ps_role")
                    config.hub.suppress_fact_warnings = hub_data.get(
                        "suppress_fact_warnings", False
                    )

            except yaml.YAMLError:
                pass  # Use environment config on parse error

        return config

    def save(self, config_path: Optional[Path] = None) -> None:
        """Save config to YAML file."""
        path = config_path or CONFIG_PATH

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {}

        # Only save non-default values
        if self.ps_base != Path(DEFAULT_PS_BASE):
            data["ps_base"] = str(self.ps_base)
        if self.io_base != Path(DEFAULT_IO_BASE):
            data["io_base"] = str(self.io_base)
        if self.ps_cfg_home:
            data["ps_cfg_home"] = str(self.ps_cfg_home)
        if self.ps_home:
            data["ps_home"] = str(self.ps_home)
        if self.domain_user != "psadm2":
            data["domain_user"] = self.domain_user

        # Domain management settings (only save non-defaults)
        if not self.sudo_enabled:
            data["sudo_enabled"] = False
        if self.parallel_boot:
            data["parallel_boot"] = True
        if self.multi_homes:
            data["multi_homes"] = [str(p) for p in self.multi_homes]

        # Hub config
        if self.hub.url:
            hub_data = {"url": self.hub.url}
            if self.hub.node_id:
                hub_data["node_id"] = self.hub.node_id
            if self.hub.environment_id:
                hub_data["environment_id"] = self.hub.environment_id
            if self.hub.environment_name:
                hub_data["environment_name"] = self.hub.environment_name
            # Environment-level facts
            if self.hub.tier:
                hub_data["tier"] = self.hub.tier
            if self.hub.pillar:
                hub_data["pillar"] = self.hub.pillar
            if self.hub.zone:
                hub_data["zone"] = self.hub.zone
            # Node-level facts
            if self.hub.ps_role:
                hub_data["ps_role"] = self.hub.ps_role
            if self.hub.suppress_fact_warnings:
                hub_data["suppress_fact_warnings"] = True
            data["hub"] = hub_data

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    def get_ps_cfg_home(self) -> Path:
        """Get PS_CFG_HOME, inferring from ps_base if not set."""
        if self.ps_cfg_home:
            return self.ps_cfg_home
        # Default location
        return self.ps_base / "cfg"

    def get_appserv_path(self) -> Path:
        """Get path to appserver domains."""
        return self.get_ps_cfg_home() / "appserv"

    def get_prcs_path(self) -> Path:
        """Get path to process scheduler domains."""
        return self.get_ps_cfg_home() / "appserv" / "prcs"

    def get_webserv_path(self) -> Path:
        """Get path to web server domains."""
        return self.get_ps_cfg_home() / "webserv"

    def get_all_cfg_homes(self) -> list:
        """Get all PS_CFG_HOME paths (primary + multi_homes)."""
        homes = [self.get_ps_cfg_home()]
        homes.extend(self.multi_homes)
        return homes


def get_config() -> PsaConfig:
    """Get the current configuration."""
    return PsaConfig.load()
