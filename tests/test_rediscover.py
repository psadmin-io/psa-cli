"""Tests for --rediscover flag in dpk apply command."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import OpsConfig, PsaConfig


runner = CliRunner()


class TestRediscoverFlagExists:
    """Verify the apply command accepts --rediscover."""

    def test_help_shows_rediscover(self):
        result = runner.invoke(psa_app, ["dpk", "apply", "--help"])
        assert result.exit_code == 0
        assert "--rediscover" in result.output


class TestRediscoverAfterApply:
    """Test --rediscover triggers OPS push after successful puppet apply."""

    def _build_dpk_tree(self, tmp_path):
        """Create minimal DPK dir structure so apply doesn't bail early.

        Layout mirrors real DPK:
            tmp_path/
              dpk/                  ← this is the --dpk-path
                puppet/
                  production/manifests/site.pp
              psft_puppet_agent/    ← code looks at dpk_path.parent for this
                bin/puppet
        """
        dpk = tmp_path / "dpk"
        puppet = dpk / "puppet"
        manifests = puppet / "production" / "manifests"
        manifests.mkdir(parents=True)
        (manifests / "site.pp").write_text("# noop")
        # Puppet binary lives alongside dpk dir (at dpk_path.parent)
        puppet_bin = tmp_path / "psft_puppet_agent" / "bin"
        puppet_bin.mkdir(parents=True)
        pb = puppet_bin / "puppet"
        pb.write_text("#!/bin/sh\nexit 0\n")
        pb.chmod(0o755)
        return dpk

    @patch("psa.commands.dpk.core.get_config")
    @patch("psa.commands.dpk.core.subprocess.run")
    @patch("psa.commands.discover._push_to_api")
    def test_push_called_with_rediscover(self, mock_push, mock_run, mock_get_config, tmp_path):
        dpk_path = self._build_dpk_tree(tmp_path)

        ops_cfg = OpsConfig(url="http://ops:8002", environment_id="env1")
        cfg = PsaConfig(ps_cfg_home=tmp_path, ops=ops_cfg)
        mock_get_config.return_value = cfg

        # puppet returns success
        mock_run.return_value = MagicMock(returncode=0)
        mock_push.return_value = {"domains_created": 1, "domains_updated": 0, "domains_unchanged": 0}

        result = runner.invoke(
            psa_app,
            ["dpk", "apply", "--dpk-path", str(dpk_path), "--rediscover"],
        )

        # apply should succeed (exit 0) and _push_to_api should have been called
        assert result.exit_code == 0, result.output
        mock_push.assert_called_once()

    @patch("psa.commands.dpk.core.get_config")
    @patch("psa.commands.dpk.core.subprocess.run")
    @patch("psa.commands.discover._push_to_api")
    def test_push_not_called_without_flag(self, mock_push, mock_run, mock_get_config, tmp_path):
        dpk_path = self._build_dpk_tree(tmp_path)

        ops_cfg = OpsConfig(url="http://ops:8002", environment_id="env1")
        cfg = PsaConfig(ps_cfg_home=tmp_path, ops=ops_cfg)
        mock_get_config.return_value = cfg

        mock_run.return_value = MagicMock(returncode=0)

        result = runner.invoke(
            psa_app,
            ["dpk", "apply", "--dpk-path", str(dpk_path)],
        )

        assert result.exit_code == 0, result.output
        mock_push.assert_not_called()

    @patch("psa.commands.dpk.core.get_config")
    @patch("psa.commands.dpk.core.subprocess.run")
    def test_ops_not_configured_warns(self, mock_run, mock_get_config, tmp_path):
        """--rediscover with no OPS config prints warning, does not crash."""
        dpk_path = self._build_dpk_tree(tmp_path)

        # OPS NOT configured (no url)
        cfg = PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig())
        mock_get_config.return_value = cfg

        mock_run.return_value = MagicMock(returncode=0)

        result = runner.invoke(
            psa_app,
            ["dpk", "apply", "--dpk-path", str(dpk_path), "--rediscover"],
        )

        assert result.exit_code == 0, result.output
        assert "not configured" in result.output.lower() or "OPS" in result.output
