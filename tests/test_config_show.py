"""Tests for psa config show command."""

from pathlib import Path
from unittest.mock import patch, PropertyMock

from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


def _invoke_show(config):
    fake_path = Path("/fake/.config/psa/config.yaml")
    with patch("psa.commands.config.PsaConfig.load", return_value=config), \
         patch("psa.commands.config.CONFIG_PATH", fake_path), \
         patch.object(Path, "exists", return_value=True):
        return runner.invoke(psa_app, ["config", "show"])


class TestConfigShowPaths:
    def test_shows_ps_app_home(self):
        cfg = PsaConfig(ps_app_home=Path("/u01/app/psoft/app"))
        result = _invoke_show(cfg)
        assert "PS_APP_HOME: /u01/app/psoft/app" in result.output

    def test_shows_ps_cust_home(self):
        cfg = PsaConfig(ps_cust_home=Path("/u01/app/psoft/cust"))
        result = _invoke_show(cfg)
        assert "PS_CUST_HOME: /u01/app/psoft/cust" in result.output

    def test_shows_multi_homes(self):
        cfg = PsaConfig(multi_homes=[Path("/cfg1"), Path("/cfg2")])
        result = _invoke_show(cfg)
        assert "Multi-homes: /cfg1, /cfg2" in result.output

    def test_hides_optional_paths_when_unset(self):
        cfg = PsaConfig()
        result = _invoke_show(cfg)
        assert "PS_APP_HOME" not in result.output
        assert "PS_CUST_HOME" not in result.output
        assert "Multi-homes" not in result.output


class TestConfigShowOptions:
    def test_shows_defaults(self):
        cfg = PsaConfig()
        result = _invoke_show(cfg)
        assert "sudo_enabled: True" in result.output
        assert "parallel_boot: False" in result.output
        assert "skip_domain_confirm: False" in result.output

    def test_shows_non_defaults(self):
        cfg = PsaConfig(sudo_enabled=False, parallel_boot=True, skip_domain_confirm=True)
        result = _invoke_show(cfg)
        assert "sudo_enabled: False" in result.output
        assert "parallel_boot: True" in result.output
        assert "skip_domain_confirm: True" in result.output


class TestConfigShowOps:
    def test_shows_zone(self):
        cfg = PsaConfig(ops=OpsConfig(url="http://ops:8000", zone="zone1"))
        result = _invoke_show(cfg)
        assert "Zone: zone1" in result.output

    def test_shows_suppress_fact_warnings(self):
        cfg = PsaConfig(ops=OpsConfig(url="http://ops:8000", suppress_fact_warnings=True))
        result = _invoke_show(cfg)
        assert "Suppress fact warnings: True" in result.output

    def test_hides_zone_when_unset(self):
        cfg = PsaConfig(ops=OpsConfig(url="http://ops:8000"))
        result = _invoke_show(cfg)
        assert "Zone" not in result.output

    def test_hides_suppress_when_false(self):
        cfg = PsaConfig(ops=OpsConfig(url="http://ops:8000", suppress_fact_warnings=False))
        result = _invoke_show(cfg)
        assert "Suppress fact warnings" not in result.output
