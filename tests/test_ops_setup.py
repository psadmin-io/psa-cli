"""Tests for psa ops setup command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


class TestOpsSetup:
    """Test that 'psa ops setup --url' invokes ops-mode init."""

    @patch("psa.commands.init._init_ops_mode")
    @patch("psa.commands.init.get_config")
    def test_ops_setup_calls_ops_mode(self, mock_get_config, mock_ops_mode):
        mock_config = PsaConfig(ops=OpsConfig())
        mock_get_config.return_value = mock_config

        result = runner.invoke(psa_app, ["ops", "setup", "--url", "http://ops:8000", "--role", "app", "--yes"])

        mock_ops_mode.assert_called_once_with(
            mock_config, "http://ops:8000", None, "app", True, False
        )

    @patch("psa.commands.init._init_ops_mode")
    @patch("psa.commands.init.get_config")
    def test_ops_setup_passes_environment_id(self, mock_get_config, mock_ops_mode):
        mock_config = PsaConfig(ops=OpsConfig())
        mock_get_config.return_value = mock_config

        result = runner.invoke(psa_app, [
            "ops", "setup",
            "--url", "http://ops:8000",
            "--environment-id", "env-123",
            "--role", "web",
            "--yes",
        ])

        mock_ops_mode.assert_called_once_with(
            mock_config, "http://ops:8000", "env-123", "web", True, False
        )

    @patch("psa.commands.init._init_ops_mode")
    @patch("psa.commands.init.get_config")
    def test_ops_setup_skip_domains_flag(self, mock_get_config, mock_ops_mode):
        mock_config = PsaConfig(ops=OpsConfig())
        mock_get_config.return_value = mock_config

        runner.invoke(psa_app, [
            "ops", "setup",
            "--url", "http://ops:8000",
            "--role", "app", "--yes", "--skip-domains",
        ])

        mock_ops_mode.assert_called_once_with(
            mock_config, "http://ops:8000", None, "app", True, True
        )

    def test_ops_setup_requires_url(self):
        result = runner.invoke(psa_app, ["ops", "setup"])
        assert result.exit_code != 0


class TestConfigSetupStandalone:
    """Test that 'psa config setup' stays standalone-only."""

    @patch("psa.commands.init._init_standalone_mode")
    @patch("psa.commands.init.get_config")
    def test_config_setup_calls_standalone(self, mock_get_config, mock_standalone):
        mock_config = PsaConfig(ops=OpsConfig())
        mock_get_config.return_value = mock_config

        result = runner.invoke(psa_app, ["config", "setup", "--yes"])

        mock_standalone.assert_called_once_with(mock_config, None, None, True)
