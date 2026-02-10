"""Tests for domain discovery logic in psa.core.domain."""

from pathlib import Path

import pytest

from psa.core.config import OpsConfig, PsaConfig
from psa.core.domain import DomainDiscovery, DomainInfo


class TestDiscoverAppDomains:
    """Test appserver domain discovery."""

    def test_discovers_app_domain(self, mock_config, tmp_cfg_home):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_appserver_domains()

        assert len(domains) == 1
        dom = domains[0]
        assert dom.name == "TESTDOM"
        assert dom.domain_type == "app"
        assert dom.path == tmp_cfg_home / "appserv" / "TESTDOM"
        assert dom.ps_cfg_home == tmp_cfg_home

    def test_app_config_values(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_appserver_domains()
        cfg = domains[0].config

        assert cfg["db_name"] == "HCMPRD"
        assert cfg["db_type"] == "ORACLE"
        assert cfg["domain_id"] == "HCMPRD_app"
        assert cfg["jolt_port"] == "9100"
        assert cfg["jolt_address"] == "//0.0.0.0:9100"

    def test_skips_special_dirs(self, mock_config, tmp_cfg_home):
        """Dirs named prcs/search/piaconfig under appserv are skipped."""
        # prcs already exists from fixture; add search
        (tmp_cfg_home / "appserv" / "search").mkdir()
        (tmp_cfg_home / "appserv" / "piaconfig").mkdir()

        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_appserver_domains()
        names = [d.name for d in domains]
        assert "prcs" not in names
        assert "search" not in names
        assert "piaconfig" not in names


class TestDiscoverPrcsDomains:
    """Test PRCS domain discovery."""

    def test_discovers_prcs_domain(self, mock_config, tmp_cfg_home):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_prcs_domains()

        assert len(domains) == 1
        dom = domains[0]
        assert dom.name == "TESTPRCS"
        assert dom.domain_type == "prcs"
        assert dom.path == tmp_cfg_home / "appserv" / "prcs" / "TESTPRCS"

    def test_prcs_config_values(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_prcs_domains()
        cfg = domains[0].config

        assert cfg["db_name"] == "HCMPRD"
        assert cfg["db_type"] == "ORACLE"
        assert cfg["prcs_server_name"] == "PSUNX"


class TestDiscoverPiaDomains:
    """Test PIA domain discovery."""

    def test_discovers_pia_domain(self, mock_config, tmp_cfg_home):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_pia_domains()

        assert len(domains) == 1
        dom = domains[0]
        assert dom.name == "TESTPIA"
        assert dom.domain_type == "pia"
        assert dom.path == tmp_cfg_home / "webserv" / "TESTPIA"

    def test_pia_config_values(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_pia_domains()
        cfg = domains[0].config

        assert cfg["app_server"] == "APPDOM"
        assert cfg["jolt_port"] == "9100"
        assert cfg["web_profile"] == "HCM"


class TestDiscoverAll:
    """Test discover_all finds all domain types."""

    def test_finds_all_types(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_all()

        types = {d.domain_type for d in domains}
        assert types == {"app", "prcs", "pia"}
        assert len(domains) == 3

    def test_returns_correct_names(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_all()
        names = {d.name for d in domains}
        assert names == {"TESTDOM", "TESTPRCS", "TESTPIA"}


class TestRawConfigCapture:
    """Test config_files[] contains raw file content."""

    def test_app_config_file_captured(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_appserver_domains()
        dom = domains[0]

        assert len(dom.config_files) == 1
        raw = dom.config_files[0]
        assert raw["type"] == "psappsrv.cfg"
        assert "DBName=HCMPRD" in raw["content"]
        assert raw["path"].endswith("psappsrv.cfg")

    def test_prcs_config_file_captured(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_prcs_domains()
        dom = domains[0]

        assert len(dom.config_files) == 1
        raw = dom.config_files[0]
        assert raw["type"] == "psprcs.cfg"
        assert "PrcsServerName=PSUNX" in raw["content"]

    def test_pia_config_file_captured(self, mock_config):
        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_pia_domains()
        dom = domains[0]

        assert len(dom.config_files) == 1
        raw = dom.config_files[0]
        assert raw["type"] == "configuration.properties"
        assert "psserver=APPDOM" in raw["content"]

    def test_oversized_file_skipped(self, mock_config, tmp_cfg_home):
        """Files larger than MAX_CONFIG_FILE_SIZE are not captured."""
        from psa.core.domain import MAX_CONFIG_FILE_SIZE

        big_cfg = tmp_cfg_home / "appserv" / "BIGDOM"
        big_cfg.mkdir(parents=True)
        cfg_file = big_cfg / "psappsrv.cfg"
        # Write a valid INI that exceeds size limit
        cfg_file.write_text("[Startup]\nDBName=X\n" + "x" * (MAX_CONFIG_FILE_SIZE + 1))

        discovery = DomainDiscovery(mock_config)
        domains = discovery.discover_appserver_domains()
        big_dom = [d for d in domains if d.name == "BIGDOM"][0]
        assert len(big_dom.config_files) == 0


class TestEmptyCfgHome:
    """Test discovery with empty PS_CFG_HOME."""

    def test_no_domains_returns_empty(self, tmp_path):
        config = PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig())
        discovery = DomainDiscovery(config)
        assert discovery.discover_all() == []

    def test_empty_appserv(self, tmp_path):
        (tmp_path / "appserv").mkdir()
        config = PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig())
        discovery = DomainDiscovery(config)
        assert discovery.discover_appserver_domains() == []

    def test_empty_webserv(self, tmp_path):
        (tmp_path / "webserv").mkdir()
        config = PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig())
        discovery = DomainDiscovery(config)
        assert discovery.discover_pia_domains() == []


class TestDomainInfoToDict:
    """Test DomainInfo.to_dict serialization."""

    def test_to_dict_fields(self, mock_config, tmp_cfg_home):
        discovery = DomainDiscovery(mock_config)
        dom = discovery.discover_appserver_domains()[0]
        d = dom.to_dict()

        assert d["name"] == "TESTDOM"
        assert d["type"] == "app"
        assert d["path"] == str(tmp_cfg_home / "appserv" / "TESTDOM")
        assert d["ps_cfg_home"] == str(tmp_cfg_home)
        assert isinstance(d["config"], dict)
        assert isinstance(d["config_files"], list)
