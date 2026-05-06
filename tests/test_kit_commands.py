"""Tests for psa kit commands."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.commands.kit import (
    PSA_KIT_REPO_SSH,
    _resolve_dpk_cust_home,
    _resolve_kit_path,
    _scaffold_dpk_cust_home,
    app,
    kit_install,
    kit_status,
    kit_update,
)
from psa.core.config import DEFAULT_DPK_CUST_HOME, DEFAULT_PSA_KIT, PsaConfig

runner = CliRunner()


# --- _resolve_kit_path tests ---


def test_resolve_kit_path_cli_arg(tmp_path):
    """CLI --dest takes priority."""
    dest = tmp_path / "my-kit"
    assert _resolve_kit_path(dest) == dest.resolve()


def test_resolve_kit_path_env(monkeypatch, tmp_path):
    """$PSA_KIT env var used when no CLI arg."""
    monkeypatch.setenv("PSA_KIT", str(tmp_path / "env-kit"))
    assert _resolve_kit_path() == tmp_path / "env-kit"


def test_resolve_kit_path_config(monkeypatch, tmp_path):
    """Config psa_kit_path used when no env."""
    monkeypatch.delenv("PSA_KIT", raising=False)
    config = PsaConfig()
    config.psa_kit_path = tmp_path / "cfg-kit"
    with patch("psa.commands.kit.get_config", return_value=config):
        assert _resolve_kit_path() == tmp_path / "cfg-kit"


def test_resolve_kit_path_default(monkeypatch):
    """Falls back to DEFAULT_PSA_KIT."""
    monkeypatch.delenv("PSA_KIT", raising=False)
    config = PsaConfig()
    with patch("psa.commands.kit.get_config", return_value=config):
        assert _resolve_kit_path() == Path(DEFAULT_PSA_KIT)


# --- _scaffold_dpk_cust_home tests ---


def test_scaffold_creates_dirs(tmp_path):
    """Scaffold creates expected directory structure."""
    cust = tmp_path / "cust"
    _scaffold_dpk_cust_home(cust)

    data_base = cust / "dpk" / "puppet" / "production" / "data"
    assert data_base.exists()
    assert (data_base / "tier").is_dir()
    assert (data_base / "env").is_dir()
    assert (data_base / "server").is_dir()
    assert (data_base / "domain").is_dir()
    assert (data_base / "zone").is_dir()
    assert (cust / "dpk" / "puppet" / "production" / "modules").is_dir()


def test_scaffold_creates_readme(tmp_path):
    """Scaffold creates README files."""
    cust = tmp_path / "cust"
    _scaffold_dpk_cust_home(cust)

    assert (cust / "README.md").exists()
    assert "DPK_CUST_HOME" in (cust / "README.md").read_text()


def test_scaffold_creates_examples(tmp_path):
    """Scaffold creates example YAML files."""
    cust = tmp_path / "cust"
    _scaffold_dpk_cust_home(cust)

    data_base = cust / "dpk" / "puppet" / "production" / "data"
    assert (data_base / "common.yaml.example").exists()
    assert (data_base / "tier" / "DEV.yaml.example").exists()
    assert (data_base / "env" / "FSCMDEV.yaml.example").exists()


def test_scaffold_idempotent(tmp_path):
    """Running scaffold twice does not overwrite existing files."""
    cust = tmp_path / "cust"
    _scaffold_dpk_cust_home(cust)

    # Modify a file
    readme = cust / "README.md"
    readme.write_text("custom content")

    _scaffold_dpk_cust_home(cust)
    assert readme.read_text() == "custom content"


# --- kit status tests ---


def test_kit_status_not_installed(monkeypatch, tmp_path):
    """Status shows hint when not installed."""
    monkeypatch.delenv("PSA_KIT", raising=False)
    config = PsaConfig()
    config.psa_kit_path = tmp_path / "nonexistent"
    with patch("psa.commands.kit.get_config", return_value=config):
        result = runner.invoke(app, ["status", "--dest", str(tmp_path / "nonexistent")])
    assert "not installed" in result.output.lower()


def test_kit_status_installed(tmp_path, kit_source):
    """Status shows version, modules, cust path when installed."""
    config = PsaConfig()
    config.dpk_cust_home = tmp_path / "cust"
    with patch("psa.commands.kit.get_config", return_value=config):
        result = runner.invoke(app, ["status", "--dest", str(kit_source)])
    assert "io_profile" in result.output
    assert "io_role" in result.output
    assert "io_tools" in result.output


# --- kit install tests ---


def test_kit_install_git_clone(monkeypatch, tmp_path):
    """Install --source git calls git clone and scaffolds cust."""
    dest = tmp_path / "kit"
    cust = tmp_path / "cust"
    monkeypatch.delenv("PSA_KIT", raising=False)
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))

    config = PsaConfig()
    save_calls = []
    orig_save = config.save
    def tracking_save(path=None):
        save_calls.append(True)
        orig_save(tmp_path / "config.yaml")
    config.save = tracking_save

    with patch("psa.commands.kit.get_config", return_value=config), \
         patch("subprocess.run", mock_run):
        result = runner.invoke(app, [
            "install",
            "--source", "git",
            "--dest", str(dest),
            "--cust", str(cust),
            "--branch", "v1.0.0",
        ])

    # git clone was called
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "git"
    assert call_args[1] == "clone"
    assert "--branch" in call_args
    assert "v1.0.0" in call_args
    assert PSA_KIT_REPO_SSH in call_args

    # Cust was scaffolded
    data_base = cust / "dpk" / "puppet" / "production" / "data"
    assert data_base.exists()
    assert (cust / "README.md").exists()

    # Config was saved
    assert len(save_calls) >= 1


def test_kit_install_nonempty_dest_fails(tmp_path):
    """Install to non-empty dir returns error."""
    dest = tmp_path / "kit"
    dest.mkdir()
    (dest / "existing-file").write_text("stuff")

    config = PsaConfig()
    with patch("psa.commands.kit.get_config", return_value=config):
        result = runner.invoke(app, [
            "install", "--dest", str(dest), "--cust", str(tmp_path / "cust"),
        ])
    assert result.exit_code != 0
    assert "not empty" in result.output.lower()


def test_kit_install_warns_existing_cust(monkeypatch, tmp_path):
    """Install warns if DPK_CUST_HOME already has files."""
    dest = tmp_path / "kit"
    cust = tmp_path / "cust"
    cust.mkdir(parents=True)
    (cust / "existing.yaml").write_text("data")

    monkeypatch.delenv("PSA_KIT", raising=False)
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    config = PsaConfig()
    config.save = lambda path=None: None  # no-op save

    with patch("psa.commands.kit.get_config", return_value=config), \
         patch("subprocess.run", mock_run):
        result = runner.invoke(app, [
            "install", "--source", "git", "--dest", str(dest), "--cust", str(cust),
        ])

    assert "already has files" in result.output.lower() or "skipping scaffold" in result.output.lower()


# --- kit update tests ---


def test_kit_update_not_installed(tmp_path):
    """Update when not installed returns error."""
    config = PsaConfig()
    with patch("psa.commands.kit.get_config", return_value=config):
        result = runner.invoke(app, ["update", "--dest", str(tmp_path / "nonexistent")])
    assert result.exit_code != 0
    assert "not installed" in result.output.lower()


def test_kit_update_git_managed(tmp_path):
    """Update on git-managed install runs git pull."""
    dest = tmp_path / "kit"
    dest.mkdir()
    (dest / ".git").mkdir()  # fake git dir

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="Already up to date.", stderr=""))
    config = PsaConfig()

    with patch("psa.commands.kit.get_config", return_value=config), \
         patch("subprocess.run", mock_run):
        result = runner.invoke(app, ["update", "--dest", str(dest)])

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args == ["git", "pull"]
