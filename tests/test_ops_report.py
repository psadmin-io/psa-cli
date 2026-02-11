"""Tests for psa ops report command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.api import ApiError
from psa.core.config import OpsConfig, PsaConfig
from psa.core.domain import DomainInfo

runner = CliRunner()


def _make_domains():
    return [
        DomainInfo(
            name="APPDOM",
            domain_type="app",
            path=Path("/fake/appserv/APPDOM"),
            ps_cfg_home=Path("/fake/cfg"),
            config={"db_name": "HCMPRD"},
        ),
        DomainInfo(
            name="PRCSDOM",
            domain_type="prcs",
            path=Path("/fake/appserv/prcs/PRCSDOM"),
            ps_cfg_home=Path("/fake/cfg"),
            config={"db_name": "HCMPRD"},
        ),
    ]


class TestOpsReportNotConfigured:
    """Test error when OPS is not configured."""

    @patch("psa.commands.ops.get_config")
    def test_exits_with_error(self, mock_get_config):
        mock_get_config.return_value = PsaConfig(ops=OpsConfig())

        result = runner.invoke(psa_app, ["ops", "report"])
        assert result.exit_code == 1
        assert "OPS not configured" in result.output


class TestOpsReportSuccess:
    """Test successful report flow."""

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_reports_and_caches(
        self, mock_get_config, mock_hostname, mock_discover, mock_api_cls, mock_cache
    ):
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="env1")
        )
        mock_discover.return_value = _make_domains()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.return_value = {
            "domains_created": 2,
            "domains_updated": 0,
            "domains_unchanged": 0,
            "configs_created": 2,
            "domains": [
                {"id": "d1-uuid", "name": "APPDOM", "domain_type": "app"},
                {"id": "d2-uuid", "name": "PRCSDOM", "domain_type": "prcs"},
            ],
        }

        result = runner.invoke(psa_app, ["ops", "report"])
        assert result.exit_code == 0
        assert "2 created" in result.output
        assert "2 config versions" in result.output

        # Verify ingest was called with correct args
        mock_client.ingest_scan.assert_called_once()
        call_kwargs = mock_client.ingest_scan.call_args[1]
        assert call_kwargs["hostname"] == "testhost"
        assert call_kwargs["environment_id"] == "env1"
        assert len(call_kwargs["domains"]) == 2

        # Verify cache was updated
        mock_cache.assert_called_once()

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_no_cache_update_without_domains_key(
        self, mock_get_config, mock_hostname, mock_discover, mock_api_cls, mock_cache
    ):
        """If API response lacks 'domains' key, skip cache update."""
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="env1")
        )
        mock_discover.return_value = _make_domains()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.return_value = {
            "domains_created": 0,
            "domains_updated": 2,
            "domains_unchanged": 0,
        }

        result = runner.invoke(psa_app, ["ops", "report"])
        assert result.exit_code == 0
        mock_cache.assert_not_called()


class TestOpsReportTypeFilter:
    """Test --type flag filters discovery."""

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_type_passed_to_discovery(
        self, mock_get_config, mock_hostname, mock_discover, mock_api_cls, mock_cache
    ):
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="env1")
        )
        mock_discover.return_value = [_make_domains()[0]]

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.return_value = {
            "domains_created": 1,
            "domains_updated": 0,
            "domains_unchanged": 0,
        }

        result = runner.invoke(psa_app, ["ops", "report", "--type", "app"])
        assert result.exit_code == 0

        # Verify run_discovery was called with type
        call_args = mock_discover.call_args
        assert call_args[0][1] == "app" or call_args[1].get("domain_type") == "app"


class TestOpsReportApiError:
    """Test API error handling."""

    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_api_error_exits_1(
        self, mock_get_config, mock_hostname, mock_discover, mock_api_cls
    ):
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="env1")
        )
        mock_discover.return_value = _make_domains()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.side_effect = ApiError("server error", status_code=500)

        result = runner.invoke(psa_app, ["ops", "report"])
        assert result.exit_code == 1
        assert "Report failed" in result.output

    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_ingest_errors_in_response(
        self, mock_get_config, mock_hostname, mock_discover, mock_api_cls
    ):
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="env1")
        )
        mock_discover.return_value = _make_domains()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.return_value = {
            "errors": ["Invalid domain data"],
        }

        result = runner.invoke(psa_app, ["ops", "report"])
        assert result.exit_code == 1
        assert "Invalid domain data" in result.output


class TestOpsReportNoDomains:
    """Test when no domains are found."""

    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_no_domains_found(self, mock_get_config, mock_hostname, mock_discover):
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="env1")
        )
        mock_discover.return_value = []

        result = runner.invoke(psa_app, ["ops", "report"])
        assert result.exit_code == 0
        assert "No domains found" in result.output


class TestOpsReportEnvironmentOverride:
    """Test --environment-id override."""

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.run_discovery")
    @patch("psa.commands.ops.get_hostname", return_value="testhost")
    @patch("psa.commands.ops.get_config")
    def test_env_id_override(
        self, mock_get_config, mock_hostname, mock_discover, mock_api_cls, mock_cache
    ):
        mock_get_config.return_value = PsaConfig(
            ops=OpsConfig(url="http://ops:8002", environment_id="default-env")
        )
        mock_discover.return_value = _make_domains()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.return_value = {
            "domains_created": 0,
            "domains_updated": 2,
            "domains_unchanged": 0,
        }

        result = runner.invoke(
            psa_app, ["ops", "report", "--environment-id", "override-env"]
        )
        assert result.exit_code == 0

        call_kwargs = mock_client.ingest_scan.call_args[1]
        assert call_kwargs["environment_id"] == "override-env"
