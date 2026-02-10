"""Tests for psa config compare command."""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import HubConfig, PsaConfig

runner = CliRunner()

MOCK_COMPARE_RESULT = {
    "rows": [
        {"key": "DBName", "values": {"APPDOM1": "HCMPRD", "APPDOM2": "HCMPRD"}, "status": "same"},
        {"key": "Port", "values": {"APPDOM1": "9100", "APPDOM2": "9200"}, "status": "different"},
        {"key": "Pool", "values": {"APPDOM1": "POOL1", "APPDOM2": None}, "status": "missing"},
    ]
}


@pytest.fixture
def hub_config():
    return PsaConfig(hub=HubConfig(url="http://hub:8002"))


class TestConfigCompare:
    @patch("psa.commands.config.get_config")
    @patch("psa.commands.config.HubClient")
    @patch("psa.commands.config.get_cached_domain_id")
    def test_compare_happy_path(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.side_effect = lambda name, **kw: {"APPDOM1": "d1", "APPDOM2": "d2"}.get(name)

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.compare_configs.return_value = MOCK_COMPARE_RESULT

        result = runner.invoke(psa_app, ["config", "compare", "APPDOM1", "APPDOM2"])
        assert result.exit_code == 0
        # Default: should NOT show "same" rows
        assert "DBName" not in result.output
        assert "Port" in result.output or "different" in result.output
        # Summary line
        assert "1 same" in result.output
        assert "1 different" in result.output
        assert "1 missing" in result.output

    @patch("psa.commands.config.get_config")
    @patch("psa.commands.config.HubClient")
    @patch("psa.commands.config.get_cached_domain_id")
    def test_compare_all_flag(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.side_effect = lambda name, **kw: {"APPDOM1": "d1", "APPDOM2": "d2"}.get(name)

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.compare_configs.return_value = MOCK_COMPARE_RESULT

        result = runner.invoke(psa_app, ["config", "compare", "APPDOM1", "APPDOM2", "--all"])
        assert result.exit_code == 0
        # --all should show same rows too
        assert "DBName" in result.output

    @patch("psa.commands.config.get_config")
    @patch("psa.commands.config.HubClient")
    @patch("psa.commands.config.get_cached_domain_id")
    def test_compare_json_output(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.side_effect = lambda name, **kw: {"APPDOM1": "d1", "APPDOM2": "d2"}.get(name)

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.compare_configs.return_value = MOCK_COMPARE_RESULT

        result = runner.invoke(psa_app, ["config", "compare", "APPDOM1", "APPDOM2", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "rows" in data

    @patch("psa.commands.config.get_config")
    def test_compare_too_few_domains(self, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        result = runner.invoke(psa_app, ["config", "compare", "ONLY_ONE"])
        assert result.exit_code == 1
        assert "At least 2" in result.output

    def test_compare_hub_not_configured(self):
        with patch("psa.commands.config.get_config") as mock_cfg:
            mock_cfg.return_value = PsaConfig(hub=HubConfig())
            result = runner.invoke(psa_app, ["config", "compare", "A", "B"])
            assert result.exit_code == 1
            assert "Hub not configured" in result.output

    @patch("psa.commands.config.get_config")
    @patch("psa.commands.config.HubClient")
    @patch("psa.commands.config.get_cached_domain_id")
    def test_compare_with_type_flag(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.side_effect = lambda name, **kw: {"A": "d1", "B": "d2"}.get(name)

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.compare_configs.return_value = {"rows": []}

        result = runner.invoke(psa_app, ["config", "compare", "A", "B", "--type", "psappsrv.cfg"])
        assert result.exit_code == 0
        mock_client.compare_configs.assert_called_once_with(["d1", "d2"], "psappsrv.cfg")

    @patch("psa.commands.config.get_config")
    @patch("psa.commands.config.HubClient")
    @patch("psa.commands.config.get_cached_domain_id")
    def test_compare_resolves_via_api_on_cache_miss(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        # Cache returns None for both
        mock_cache.return_value = None

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.resolve_domain.side_effect = [
            {"id": "d1", "name": "A"},
            {"id": "d2", "name": "B"},
        ]
        mock_client.compare_configs.return_value = {"rows": []}

        result = runner.invoke(psa_app, ["config", "compare", "A", "B"])
        assert result.exit_code == 0
        assert mock_client.resolve_domain.call_count == 2
