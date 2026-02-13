"""Tests for consolidated DPK commands (setup --prereq/--postcfg, sync --hiera/--site/--modules)."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app

runner = CliRunner()


# --- Fixtures ---


@pytest.fixture
def mock_dpk_install(tmp_path):
    """Create a mock DPK install dir with setup script."""
    setup_dir = tmp_path / "setup"
    setup_dir.mkdir()
    script = setup_dir / "psft-dpk-setup.sh"
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)
    return tmp_path


@pytest.fixture
def mock_dpk_dir(tmp_path):
    """Create a mock DPK directory with puppet structure for sync tests."""
    dpk = tmp_path / "dpk"
    puppet = dpk / "puppet"
    prod = puppet / "production"
    manifests = prod / "manifests"
    modules = prod / "modules"
    manifests.mkdir(parents=True)
    modules.mkdir(parents=True)
    # Create existing files so backup paths work
    (puppet / "hiera.yaml").write_text("old hiera")
    (prod / "hiera.yaml").write_text("old hiera")
    (manifests / "site.pp").write_text("old site")
    return dpk


@pytest.fixture
def mock_source_dir(tmp_path):
    """Create a mock source dir with io_profile/io_role modules."""
    src = tmp_path / "source"
    mod_dir = src / "dpk" / "puppet" / "production" / "modules"
    (mod_dir / "io_profile").mkdir(parents=True)
    (mod_dir / "io_profile" / "init.pp").write_text("class io_profile {}")
    (mod_dir / "io_role").mkdir(parents=True)
    (mod_dir / "io_role" / "init.pp").write_text("class io_role {}")
    return src


# ==================== setup --prereq / --postcfg ====================


class TestSetupPrereqPostcfg:
    def test_prereq_and_postcfg_mutually_exclusive(self, mock_dpk_install):
        """Both --prereq and --postcfg together should exit 1."""
        result = runner.invoke(psa_app, [
            "dpk", "setup",
            "--prereq", "--postcfg",
            "--install-dir", str(mock_dpk_install),
            "--base-dir", "/tmp/base",
        ])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    @patch("os.geteuid", return_value=0)
    def test_prereq_dry_run(self, mock_euid, mock_dpk_install):
        """--prereq --dry-run shows command without executing."""
        result = runner.invoke(psa_app, [
            "dpk", "setup",
            "--prereq", "--dry-run",
            "--install-dir", str(mock_dpk_install),
        ])
        assert result.exit_code == 0
        assert "--prereq" in result.output
        assert "Dry run" in result.output

    @patch("os.geteuid", return_value=0)
    def test_postcfg_dry_run(self, mock_euid, mock_dpk_install):
        """--postcfg --dry-run shows command without executing."""
        result = runner.invoke(psa_app, [
            "dpk", "setup",
            "--postcfg", "--dry-run",
            "--install-dir", str(mock_dpk_install),
            "--base-dir", "/tmp/base",
        ])
        assert result.exit_code == 0
        assert "--postcfg" in result.output
        assert "Dry run" in result.output

    @patch("psa.commands.dpk.core._check_dpk_prerequisites")
    def test_setup_default_dry_run(self, mock_prereqs, mock_dpk_install):
        """Default setup (no --prereq/--postcfg) with --dry-run still works."""
        result = runner.invoke(psa_app, [
            "dpk", "setup",
            "--dry-run",
            "--install-dir", str(mock_dpk_install),
            "--base-dir", "/tmp/base",
        ])
        assert result.exit_code == 0
        assert "--silent" in result.output
        assert "Dry run" in result.output


# ==================== sync --hiera / --site / --modules ====================


class TestSyncFilters:
    def test_sync_hiera_only(self, mock_dpk_dir, mock_source_dir):
        """--hiera only deploys hiera.yaml, not site.pp or modules."""
        result = runner.invoke(psa_app, [
            "dpk", "sync",
            "--hiera",
            "--dpk-path", str(mock_dpk_dir),
            "--source", str(mock_source_dir),
        ])
        assert result.exit_code == 0
        # hiera.yaml should be updated
        hiera = mock_dpk_dir / "puppet" / "production" / "hiera.yaml"
        assert "version: 5" in hiera.read_text()
        # site.pp should NOT be updated (still old content)
        site = mock_dpk_dir / "puppet" / "production" / "manifests" / "site.pp"
        assert site.read_text() == "old site"

    def test_sync_site_only(self, mock_dpk_dir, mock_source_dir):
        """--site only deploys site.pp, not hiera.yaml."""
        result = runner.invoke(psa_app, [
            "dpk", "sync",
            "--site",
            "--dpk-path", str(mock_dpk_dir),
            "--source", str(mock_source_dir),
        ])
        assert result.exit_code == 0
        # site.pp should be updated
        site = mock_dpk_dir / "puppet" / "production" / "manifests" / "site.pp"
        assert "ps_role" in site.read_text()
        # hiera.yaml should NOT be updated
        hiera = mock_dpk_dir / "puppet" / "production" / "hiera.yaml"
        assert hiera.read_text() == "old hiera"

    def test_sync_modules_only(self, mock_dpk_dir, mock_source_dir):
        """--modules only deploys modules, not hiera or site."""
        result = runner.invoke(psa_app, [
            "dpk", "sync",
            "--modules",
            "--dpk-path", str(mock_dpk_dir),
            "--source", str(mock_source_dir),
        ])
        assert result.exit_code == 0
        # modules should be deployed
        io_profile = mock_dpk_dir / "puppet" / "production" / "modules" / "io_profile"
        assert io_profile.exists()
        # hiera should NOT be updated
        hiera = mock_dpk_dir / "puppet" / "production" / "hiera.yaml"
        assert hiera.read_text() == "old hiera"
        # site should NOT be updated
        site = mock_dpk_dir / "puppet" / "production" / "manifests" / "site.pp"
        assert site.read_text() == "old site"

    def test_sync_all_default(self, mock_dpk_dir, mock_source_dir):
        """No filter flags -> deploys all three components."""
        result = runner.invoke(psa_app, [
            "dpk", "sync",
            "--dpk-path", str(mock_dpk_dir),
            "--source", str(mock_source_dir),
        ])
        assert result.exit_code == 0
        # All three should be updated
        hiera = mock_dpk_dir / "puppet" / "production" / "hiera.yaml"
        assert "version: 5" in hiera.read_text()
        site = mock_dpk_dir / "puppet" / "production" / "manifests" / "site.pp"
        assert "ps_role" in site.read_text()
        io_role = mock_dpk_dir / "puppet" / "production" / "modules" / "io_role"
        assert io_role.exists()

    def test_sync_data_flag_accepted(self, mock_dpk_dir, mock_source_dir):
        """--data flag is accepted (even if PSA-OPS not configured, it should not crash sync)."""
        result = runner.invoke(psa_app, [
            "dpk", "sync",
            "--data",
            "--dpk-path", str(mock_dpk_dir),
            "--source", str(mock_source_dir),
        ])
        # Sync of files succeeds; --data may warn about PSA-OPS not configured
        # but overall command should complete (sync catches exceptions)
        assert result.exit_code == 0


# ==================== Removed commands ====================


class TestRemovedCommands:
    def test_data_sync_removed(self):
        """'psa dpk data sync' should no longer be a valid command."""
        result = runner.invoke(psa_app, ["dpk", "data", "sync"])
        # Typer shows help or error for missing subcommand
        assert result.exit_code != 0 or "No such command" in result.output or "Usage" in result.output

    def test_hiera_command_removed(self):
        """'psa dpk hiera' should no longer be a valid command."""
        result = runner.invoke(psa_app, ["dpk", "hiera"])
        assert result.exit_code != 0 or "No such command" in result.output

    def test_prereq_command_removed(self):
        """'psa dpk prereq' should no longer be a valid command."""
        result = runner.invoke(psa_app, ["dpk", "prereq"])
        assert result.exit_code != 0 or "No such command" in result.output

    def test_postcfg_command_removed(self):
        """'psa dpk postcfg' should no longer be a valid command."""
        result = runner.invoke(psa_app, ["dpk", "postcfg"])
        assert result.exit_code != 0 or "No such command" in result.output

    def test_site_command_removed(self):
        """'psa dpk site' should no longer be a valid command."""
        result = runner.invoke(psa_app, ["dpk", "site"])
        assert result.exit_code != 0 or "No such command" in result.output

    def test_modules_command_removed(self):
        """'psa dpk modules' should no longer be a valid command."""
        result = runner.invoke(psa_app, ["dpk", "modules"])
        assert result.exit_code != 0 or "No such command" in result.output
