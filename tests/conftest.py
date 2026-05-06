"""Shared fixtures for psa-cli tests."""

from pathlib import Path

import pytest

from psa.core.config import OpsConfig, PsaConfig
from psa.core.output import Verbosity, set_verbosity


@pytest.fixture(autouse=True)
def _reset_verbosity():
    """Reset module-global verbosity before/after each test.

    psa.core.output holds verbosity in a module-global. Tests that invoke CLI
    commands with --quiet (or call set_verbosity directly) leave it stuck at
    QUIET, which silently suppresses print_info in subsequent tests and breaks
    output-dependent assertions.
    """
    set_verbosity(Verbosity.DEFAULT)
    yield
    set_verbosity(Verbosity.DEFAULT)


# --- Sample config file content ---

SAMPLE_PSAPPSRV_CFG = """\
[Startup]
DBName=HCMPRD
DBType=ORACLE

[Domain Settings]
Domain ID=HCMPRD_app

[JOLT Listener]
Port=9100
Address=//0.0.0.0:9100
"""

# Older Archive version with different port
SAMPLE_PSAPPSRV_CFG_OLD = """\
[Startup]
DBName=HCMPRD
DBType=ORACLE

[Domain Settings]
Domain ID=HCMPRD_app

[JOLT Listener]
Port=9000
Address=//0.0.0.0:9000
"""

SAMPLE_PSPRCS_CFG = """\
[Startup]
DBName=HCMPRD
DBType=ORACLE
PrcsServerName=PSUNX
"""

SAMPLE_CONFIGURATION_PROPERTIES = """\
psserver=APPDOM
psport=9100
webprofile=HCM
signon_domain_suffix=.example.com
HTTPPort=8000
"""


@pytest.fixture
def tmp_cfg_home(tmp_path):
    cfg_home = tmp_path

    app_dir = cfg_home / "appserv" / "TESTDOM"
    app_dir.mkdir(parents=True)
    (app_dir / "psappsrv.cfg").write_text(SAMPLE_PSAPPSRV_CFG)

    # Archive dir with timestamped backups
    archive_dir = app_dir / "Archive"
    archive_dir.mkdir()
    (archive_dir / "psappsrv.cfg").write_text(SAMPLE_PSAPPSRV_CFG)  # plain copy (no timestamp)
    (archive_dir / "psappsrv_012526_1430_22.cfg").write_text(SAMPLE_PSAPPSRV_CFG_OLD)  # older
    (archive_dir / "psappsrv_020126_0900_00.cfg").write_text(SAMPLE_PSAPPSRV_CFG_OLD)  # newer

    prcs_dir = cfg_home / "appserv" / "prcs" / "TESTPRCS"
    prcs_dir.mkdir(parents=True)
    (prcs_dir / "psprcs.cfg").write_text(SAMPLE_PSPRCS_CFG)

    # PIA domain (flat layout) — needs config.xml for existence detection
    pia_base = cfg_home / "webserv" / "TESTPIA"
    (pia_base / "config").mkdir(parents=True)
    (pia_base / "config" / "config.xml").write_text("<config/>")
    pia_dir = pia_base / "applications" / "peoplesoft"
    pia_dir.mkdir(parents=True)
    (pia_dir / "configuration.properties").write_text(SAMPLE_CONFIGURATION_PROPERTIES)

    # PIA domain (DPK layout) — config.properties under PORTAL.war
    dpk_base = cfg_home / "webserv" / "DPKPIA"
    (dpk_base / "config").mkdir(parents=True)
    (dpk_base / "config" / "config.xml").write_text("<config/>")
    dpk_props = dpk_base / "applications" / "peoplesoft" / "PORTAL.war" / "WEB-INF" / "psftdocs" / "ps"
    dpk_props.mkdir(parents=True)
    (dpk_props / "configuration.properties").write_text(SAMPLE_CONFIGURATION_PROPERTIES)

    return cfg_home


@pytest.fixture
def mock_config(tmp_cfg_home):
    return PsaConfig(
        ps_cfg_home=tmp_cfg_home,
        ops=OpsConfig(),
        sudo_enabled=False,
    )


# --- New fixtures for psa-kit ---


@pytest.fixture
def config_file(tmp_path):
    """Return a path for a temporary config YAML file."""
    return tmp_path / "config.yaml"


@pytest.fixture
def base_config(tmp_path, config_file):
    """Return a PsaConfig with temporary paths, saved to disk."""
    config = PsaConfig()
    config.ps_base = tmp_path / "psoft"
    config.io_base = tmp_path / "io"
    config.save(config_file)
    return config


@pytest.fixture
def dpk_tree(tmp_path):
    """Create a minimal DPK directory tree and return its root."""
    dpk = tmp_path / "dpk"
    (dpk / "puppet" / "production" / "manifests").mkdir(parents=True)
    (dpk / "puppet" / "production" / "modules").mkdir(parents=True)
    (dpk / "puppet" / "production" / "data").mkdir(parents=True)
    return dpk


@pytest.fixture
def kit_source(tmp_path):
    """Create a fake psa-kit source tree with io_* modules."""
    kit = tmp_path / "psa-kit"
    modules = kit / "dpk" / "puppet" / "production" / "modules"
    for name in ["io_profile", "io_role", "io_tools"]:
        mod_dir = modules / name
        mod_dir.mkdir(parents=True)
        (mod_dir / "init.pp").write_text(f"# {name}\n")
    # Also create data dir
    data = kit / "dpk" / "puppet" / "production" / "data" / "psa-ops"
    data.mkdir(parents=True)
    (data / "common.yaml").write_text("---\n# psa-ops defaults\n")
    return kit
