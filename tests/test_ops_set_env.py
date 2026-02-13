"""Tests for psa ops set-env command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.api import ApiError
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


def _configured_config(**kwargs):
    defaults = {"url": "http://ops:8002", "node_id": "node-uuid-1"}
    defaults.update(kwargs)
    return PsaConfig(ops=OpsConfig(**defaults))


class TestSetEnvResolvesNames:
    """Test happy path: names resolve to UUIDs and update succeeds."""

    @patch("psa.commands.ops.get_cached_domain_id", return_value=None)
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_resolves_and_assigns(self, mock_get_config, mock_api_cls, mock_cache):
        mock_get_config.return_value = _configured_config()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.list_domains.return_value = [
            {"id": "dom-uuid-1", "name": "APPDOM", "domain_type": "app"}
        ]
        mock_client.resolve_environment.return_value = {"id": "env-uuid-1", "name": "dev"}
        mock_client.update_domain.return_value = {"id": "dom-uuid-1", "name": "APPDOM"}

        result = runner.invoke(psa_app, ["ops", "set-env", "APPDOM", "dev"])
        assert result.exit_code == 0
        assert "assigned to environment" in result.output

        mock_client.list_domains.assert_called_once_with(name="APPDOM", node_id="node-uuid-1")
        mock_client.resolve_environment.assert_called_once_with("dev")
        mock_client.update_domain.assert_called_once_with("dom-uuid-1", environment_id="env-uuid-1")

    @patch("psa.commands.ops.get_cached_domain_id", return_value="cached-dom-uuid")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_uses_cached_domain_id(self, mock_get_config, mock_api_cls, mock_cache):
        mock_get_config.return_value = _configured_config()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.resolve_environment.return_value = {"id": "env-uuid-1", "name": "dev"}
        mock_client.update_domain.return_value = {"id": "cached-dom-uuid", "name": "APPDOM"}

        result = runner.invoke(psa_app, ["ops", "set-env", "APPDOM", "dev"])
        assert result.exit_code == 0

        # Should not call list_domains when cache hit
        mock_client.list_domains.assert_not_called()
        mock_client.update_domain.assert_called_once_with("cached-dom-uuid", environment_id="env-uuid-1")

    @patch("psa.commands.ops.get_cached_domain_id", return_value=None)
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_type_filter(self, mock_get_config, mock_api_cls, mock_cache):
        mock_get_config.return_value = _configured_config()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.list_domains.return_value = [
            {"id": "dom-app", "name": "APPDOM", "domain_type": "app"},
            {"id": "dom-prcs", "name": "APPDOM", "domain_type": "prcs"},
        ]
        mock_client.resolve_environment.return_value = {"id": "env-uuid-1", "name": "dev"}
        mock_client.update_domain.return_value = {"id": "dom-app", "name": "APPDOM"}

        result = runner.invoke(psa_app, ["ops", "set-env", "APPDOM", "dev", "--type", "app"])
        assert result.exit_code == 0
        mock_client.update_domain.assert_called_once_with("dom-app", environment_id="env-uuid-1")


class TestSetEnvDomainNotFound:

    @patch("psa.commands.ops.get_cached_domain_id", return_value=None)
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_domain_not_found(self, mock_get_config, mock_api_cls, mock_cache):
        mock_get_config.return_value = _configured_config()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.list_domains.return_value = []

        result = runner.invoke(psa_app, ["ops", "set-env", "NODOM", "dev"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestSetEnvEnvironmentNotFound:

    @patch("psa.commands.ops.get_cached_domain_id", return_value="dom-uuid-1")
    @patch("psa.commands.ops.ApiClient")
    @patch("psa.commands.ops.get_config")
    def test_env_not_found(self, mock_get_config, mock_api_cls, mock_cache):
        mock_get_config.return_value = _configured_config()

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.resolve_environment.return_value = None

        result = runner.invoke(psa_app, ["ops", "set-env", "APPDOM", "badenv"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestSetEnvOpsNotConfigured:

    @patch("psa.commands.ops.get_config")
    def test_not_configured(self, mock_get_config):
        mock_get_config.return_value = PsaConfig(ops=OpsConfig())

        result = runner.invoke(psa_app, ["ops", "set-env", "APPDOM", "dev"])
        assert result.exit_code == 1
        assert "not configured" in result.output
