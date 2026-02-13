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
class OpsConfig:
    """PSA-OPS connection configuration."""

    url: Optional[str] = None
    node_id: Optional[str] = None
    environment_id: Optional[str] = None
    environment_name: Optional[str] = None
    # Environment-level facts (from environment during init)
    tier: Optional[str] = None
    pillar: Optional[str] = None
    zone: Optional[str] = None
    # Node-level facts (from ops or init)
    ps_role: Optional[str] = None
    # Suppress "using config defaults" warnings
    suppress_fact_warnings: bool = False

    def is_configured(self) -> bool:
        """Check if PSA-OPS is configured."""
        return self.url is not None


@dataclass
class PsaConfig:
    """Configuration for psa tools."""

    ps_base: Path = field(default_factory=lambda: Path(DEFAULT_PS_BASE))
    io_base: Path = field(default_factory=lambda: Path(DEFAULT_IO_BASE))
    ps_cfg_home: Optional[Path] = None
    ps_home: Optional[Path] = None
    ps_app_home: Optional[Path] = None
    ps_cust_home: Optional[Path] = None
    runtime_user: str = "psadm2"
    ops: OpsConfig = field(default_factory=OpsConfig)
    # Domain management settings
    sudo_enabled: bool = True  # Use sudo to run commands as runtime_user
    parallel_boot: bool = False  # Use parallelboot instead of boot
    skip_domain_confirm: bool = False  # Skip confirmation when acting on all domains
    multi_homes: list = field(default_factory=list)  # Additional PS_CFG_HOME paths
    dpk_repo_path: Optional[str] = None  # Path to DPK file repository

    @classmethod
    def from_environment(cls) -> "PsaConfig":
        """Create config from environment variables."""
        config = cls()

        # Override from environment
        if ps_cfg_home := os.environ.get("PS_CFG_HOME"):
            config.ps_cfg_home = Path(ps_cfg_home)

        if ps_home := os.environ.get("PS_HOME"):
            config.ps_home = Path(ps_home)

        if ps_app_home := os.environ.get("PS_APP_HOME"):
            config.ps_app_home = Path(ps_app_home)

        if ps_cust_home := os.environ.get("PS_CUST_HOME"):
            config.ps_cust_home = Path(ps_cust_home)

        if ps_base := os.environ.get("PS_BASE"):
            config.ps_base = Path(ps_base)

        if io_base := os.environ.get("IO_BASE"):
            config.io_base = Path(io_base)

        # OPS API from environment
        if ops_url := os.environ.get("PSA_OPS_URL"):
            config.ops.url = ops_url

        if env_id := os.environ.get("PSA_ENVIRONMENT_ID"):
            config.ops.environment_id = env_id

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
                if ps_app_home := data.get("ps_app_home"):
                    config.ps_app_home = Path(ps_app_home)
                if ps_cust_home := data.get("ps_cust_home"):
                    config.ps_cust_home = Path(ps_cust_home)
                if runtime_user := data.get("runtime_user", data.get("domain_user")):
                    config.runtime_user = runtime_user

                # Domain management settings
                if "sudo_enabled" in data:
                    config.sudo_enabled = data["sudo_enabled"]
                if "parallel_boot" in data:
                    config.parallel_boot = data["parallel_boot"]
                if "skip_domain_confirm" in data:
                    config.skip_domain_confirm = data["skip_domain_confirm"]
                if multi_homes := data.get("multi_homes"):
                    config.multi_homes = [Path(p) for p in multi_homes]
                if dpk_repo_path := data.get("dpk_repo_path"):
                    config.dpk_repo_path = dpk_repo_path

                # OPS config (env vars take precedence)
                if ops_data := data.get("ops"):
                    if not config.ops.url:
                        config.ops.url = ops_data.get("url")
                    if not config.ops.node_id:
                        config.ops.node_id = ops_data.get("node_id")
                    if not config.ops.environment_id:
                        config.ops.environment_id = ops_data.get("environment_id")
                    config.ops.environment_name = ops_data.get("environment_name")
                    # Environment-level facts
                    config.ops.tier = ops_data.get("tier")
                    config.ops.pillar = ops_data.get("pillar")
                    config.ops.zone = ops_data.get("zone")
                    # Node-level facts
                    config.ops.ps_role = ops_data.get("ps_role")
                    config.ops.suppress_fact_warnings = ops_data.get(
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
        if self.ps_app_home:
            data["ps_app_home"] = str(self.ps_app_home)
        if self.ps_cust_home:
            data["ps_cust_home"] = str(self.ps_cust_home)
        if self.runtime_user != "psadm2":
            data["runtime_user"] = self.runtime_user

        # Domain management settings (only save non-defaults)
        if not self.sudo_enabled:
            data["sudo_enabled"] = False
        if self.parallel_boot:
            data["parallel_boot"] = True
        if self.skip_domain_confirm:
            data["skip_domain_confirm"] = True
        if self.multi_homes:
            data["multi_homes"] = [str(p) for p in self.multi_homes]
        if self.dpk_repo_path:
            data["dpk_repo_path"] = self.dpk_repo_path

        # OPS config
        if self.ops.url:
            ops_data = {"url": self.ops.url}
            if self.ops.node_id:
                ops_data["node_id"] = self.ops.node_id
            if self.ops.environment_id:
                ops_data["environment_id"] = self.ops.environment_id
            if self.ops.environment_name:
                ops_data["environment_name"] = self.ops.environment_name
            # Environment-level facts
            if self.ops.tier:
                ops_data["tier"] = self.ops.tier
            if self.ops.pillar:
                ops_data["pillar"] = self.ops.pillar
            if self.ops.zone:
                ops_data["zone"] = self.ops.zone
            # Node-level facts
            if self.ops.ps_role:
                ops_data["ps_role"] = self.ops.ps_role
            if self.ops.suppress_fact_warnings:
                ops_data["suppress_fact_warnings"] = True
            data["ops"] = ops_data

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
