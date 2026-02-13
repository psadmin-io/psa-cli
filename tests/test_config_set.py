"""Tests for psa config set command."""

from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import PsaConfig

runner = CliRunner()


class TestConfigSet:
    @patch("psa.commands.config.PsaConfig.save")
    @patch("psa.commands.config.PsaConfig.load")
    def test_set_bool_true(self, mock_load, mock_save):
        mock_load.return_value = PsaConfig()
        result = runner.invoke(psa_app, ["config", "set", "skip_domain_confirm", "true"])
        assert result.exit_code == 0
        assert "skip_domain_confirm" in result.output
        mock_save.assert_called_once()

    @patch("psa.commands.config.PsaConfig.save")
    @patch("psa.commands.config.PsaConfig.load")
    def test_set_bool_false(self, mock_load, mock_save):
        cfg = PsaConfig(skip_domain_confirm=True)
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["config", "set", "skip_domain_confirm", "false"])
        assert result.exit_code == 0
        assert cfg.skip_domain_confirm is False

    @patch("psa.commands.config.PsaConfig.save")
    @patch("psa.commands.config.PsaConfig.load")
    def test_set_string_value(self, mock_load, mock_save):
        cfg = PsaConfig()
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["config", "set", "runtime_user", "psadm3"])
        assert result.exit_code == 0
        assert cfg.runtime_user == "psadm3"

    def test_unknown_key_fails(self):
        result = runner.invoke(psa_app, ["config", "set", "bogus", "value"])
        assert result.exit_code == 1
        assert "Unknown key" in result.output

    @patch("psa.commands.config.PsaConfig.load")
    def test_invalid_bool_fails(self, mock_load):
        mock_load.return_value = PsaConfig()
        result = runner.invoke(psa_app, ["config", "set", "skip_domain_confirm", "maybe"])
        assert result.exit_code == 1
        assert "Invalid boolean" in result.output
