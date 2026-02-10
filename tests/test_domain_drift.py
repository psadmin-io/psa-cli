"""Tests for psa domain drift command."""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


@pytest.fixture
def hub_config():
    return PsaConfig(ops=OpsConfig(url="http://hub:8002"))


MOCK_DRIFT_SUMMARY = {
    "config_types": [
        {"config_type": "psappsrv.cfg", "has_drift": True, "change_count": 2, "last_capture": "2026-02-09T12:00:00"},
        {"config_type": "psprcs.cfg", "has_drift": False, "change_count": 0, "last_capture": "2026-02-09T12:00:00"},
    ]
}

MOCK_DRIFT_DETAIL = {
    "changes": [
        {"key": "Port", "old_value": "9100", "new_value": "9200", "change_type": "modified"},
        {"key": "NewKey", "old_value": None, "new_value": "val", "change_type": "added"},
    ]
}


class TestDomainDriftSummary:
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_summary_happy_path(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.return_value = "d1"

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.get_drift_summary.return_value = MOCK_DRIFT_SUMMARY

        result = runner.invoke(psa_app, ["domain", "drift", "APPDOM"])
        assert result.exit_code == 0
        assert "psappsrv.cfg" in result.output
        assert "Yes" in result.output
        assert "No" in result.output

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_summary_no_drift(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.return_value = "d1"

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.get_drift_summary.return_value = {"config_types": []}

        result = runner.invoke(psa_app, ["domain", "drift", "APPDOM"])
        assert result.exit_code == 0
        assert "No drift detected" in result.output


class TestDomainDriftDetail:
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_detail_with_type(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.return_value = "d1"

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.get_domain_drift.return_value = MOCK_DRIFT_DETAIL

        result = runner.invoke(psa_app, ["domain", "drift", "APPDOM", "--type", "psappsrv.cfg"])
        assert result.exit_code == 0
        assert "Port" in result.output
        assert "9100" in result.output
        assert "9200" in result.output

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_detail_no_changes(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.return_value = "d1"

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.get_domain_drift.return_value = {"changes": []}

        result = runner.invoke(psa_app, ["domain", "drift", "APPDOM", "--type", "psappsrv.cfg"])
        assert result.exit_code == 0
        assert "No drift detected" in result.output


class TestDomainDriftJson:
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_json_output(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.return_value = "d1"

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.get_drift_summary.return_value = MOCK_DRIFT_SUMMARY

        result = runner.invoke(psa_app, ["domain", "drift", "APPDOM", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "config_types" in data


class TestDomainDriftErrors:
    def test_hub_not_configured(self):
        with patch("psa.commands.domain.get_config") as mock_cfg:
            mock_cfg.return_value = PsaConfig(ops=OpsConfig())
            result = runner.invoke(psa_app, ["domain", "drift", "APPDOM"])
            assert result.exit_code == 1
            assert "OPS not configured" in result.output

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_domain_not_found(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        mock_get_config.return_value = hub_config
        mock_cache.return_value = None

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.resolve_domain.return_value = None

        result = runner.invoke(psa_app, ["domain", "drift", "NONEXIST"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_hub_error(self, mock_cache, mock_hub_cls, mock_get_config, hub_config):
        from psa.core.api import ApiError

        mock_get_config.return_value = hub_config
        mock_cache.return_value = "d1"

        mock_client = MagicMock()
        mock_hub_cls.return_value = mock_client
        mock_client.get_drift_summary.side_effect = ApiError("server error", status_code=500)

        result = runner.invoke(psa_app, ["domain", "drift", "APPDOM"])
        assert result.exit_code == 1
        assert "Drift check failed" in result.output
