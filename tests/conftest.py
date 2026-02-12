"""Shared fixtures for psa-cli tests."""

from pathlib import Path

import pytest

from psa.core.config import OpsConfig, PsaConfig


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
