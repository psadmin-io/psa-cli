"""Tests for psa ops register command."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import OpsConfig, PsaConfig
from psa.core.domain import DomainInfo

runner = CliRunner()


def _mk_domain(name: str, domain_type: str = "app", db_name: str = "HCMPRD") -> DomainInfo:
    return DomainInfo(
        name=name,
        domain_type=domain_type,
        path=Path(f"/u01/app/psoft/cfg/{domain_type}serv/{name}"),
        config={"db_name": db_name},
    )


MOCK_INGEST_RESULT = {
    "domains": [
        {"name": "APPDOM", "id": "d1", "type": "app"},
        {"name": "PRCSDOM", "id": "d2", "type": "prcs"},
        {"name": "WEBDOM", "id": "d3", "type": "web"},
    ]
}


@pytest.fixture
def ops_config():
    return PsaConfig(ops=OpsConfig(url="http://api:8002", environment_id="env-123", node_id="n1"))


def _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update,
                    ops_config, domains, ingest_result=MOCK_INGEST_RESULT):
    mock_get_config.return_value = ops_config
    mock_disc = MagicMock()
    mock_disc.discover_all.return_value = domains
    mock_discovery_cls.return_value = mock_disc
    mock_client = MagicMock()
    mock_api_cls.return_value = mock_client
    mock_client.ingest_scan.return_value = ingest_result
    return mock_client


class TestOpsRegister:
    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_happy_path(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        domains = [_mk_domain("APPDOM"), _mk_domain("PRCSDOM", "prcs"), _mk_domain("WEBDOM", "web")]
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, domains)

        result = runner.invoke(psa_app, ["ops", "register", "--yes"])
        assert result.exit_code == 0, result.output
        mock_client.ingest_scan.assert_called_once()
        kwargs = mock_client.ingest_scan.call_args.kwargs
        assert kwargs["environment_id"] == "env-123"
        assert len(kwargs["domains"]) == 3
        mock_cache_update.assert_called_once_with(MOCK_INGEST_RESULT)
        assert "Registered 3" in result.output

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_no_domains(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, [])

        result = runner.invoke(psa_app, ["ops", "register", "--yes"])
        assert result.exit_code == 0
        mock_client.ingest_scan.assert_not_called()
        assert "No domains found" in result.output

    @patch("psa.commands.ops.get_config")
    def test_register_not_configured(self, mock_get_config):
        mock_get_config.return_value = PsaConfig(ops=OpsConfig())
        result = runner.invoke(psa_app, ["ops", "register", "--yes"])
        assert result.exit_code == 1
        assert "not configured" in result.output.lower()

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_api_error(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        from psa.core.api import ApiError
        mock_get_config.return_value = ops_config
        mock_disc = MagicMock()
        mock_disc.discover_all.return_value = [_mk_domain("APPDOM")]
        mock_discovery_cls.return_value = mock_disc
        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.ingest_scan.side_effect = ApiError("boom")

        result = runner.invoke(psa_app, ["ops", "register", "--yes"])
        assert result.exit_code == 1
        assert "Registration failed" in result.output

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_idempotent(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        domains = [_mk_domain("APPDOM")]
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, domains)

        result1 = runner.invoke(psa_app, ["ops", "register", "--yes"])
        result2 = runner.invoke(psa_app, ["ops", "register", "--yes"])
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        assert mock_client.ingest_scan.call_count == 2

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_decline(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        domains = [_mk_domain("APPDOM"), _mk_domain("PRCSDOM", "prcs")]
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, domains)

        result = runner.invoke(psa_app, ["ops", "register"], input="n\n")
        assert result.exit_code != 0
        mock_client.ingest_scan.assert_not_called()

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_json_output(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        domains = [_mk_domain("APPDOM")]
        _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, domains)

        result = runner.invoke(psa_app, ["ops", "register", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["environment_id"] == "env-123"
        assert "hostname" in data
        assert len(data["registered"]) == 3
        assert data["registered"][0]["name"] == "APPDOM"

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_subset(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        domains = [_mk_domain("APPDOM"), _mk_domain("PRCSDOM", "prcs"), _mk_domain("WEBDOM", "web")]
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, domains)

        result = runner.invoke(psa_app, ["ops", "register", "APPDOM", "WEBDOM", "--yes"])
        assert result.exit_code == 0, result.output
        kwargs = mock_client.ingest_scan.call_args.kwargs
        sent_names = [d["name"] for d in kwargs["domains"]]
        assert sent_names == ["APPDOM", "WEBDOM"]

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_omits_status_from_payload(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        """Discovery status is filesystem-heuristic; must not clobber server status on re-ingest."""
        domain = _mk_domain("APPDOM")
        domain.status = "stopped"
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, [domain])

        result = runner.invoke(psa_app, ["ops", "register", "--yes"])
        assert result.exit_code == 0, result.output
        sent = mock_client.ingest_scan.call_args.kwargs["domains"]
        assert "status" not in sent[0]

    @patch("psa.commands.ops.update_cache_from_ingest")
    @patch("psa.commands.ops.DomainDiscovery")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_register_subset_missing(self, mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config):
        domains = [_mk_domain("APPDOM")]
        mock_client = _patch_register(mock_get_config, mock_api_cls, mock_discovery_cls, mock_cache_update, ops_config, domains)

        result = runner.invoke(psa_app, ["ops", "register", "BOGUS", "--yes"])
        assert result.exit_code == 1
        mock_client.ingest_scan.assert_not_called()
        assert "BOGUS" in result.output
