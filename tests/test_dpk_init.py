"""Tests for psa dpk init command."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.commands.dpk.init import scaffold_dpk_cust_home
from psa.core.config import PsaConfig

runner = CliRunner()


# --- scaffold_dpk_cust_home tests ---


def test_scaffold_creates_flat_layout(tmp_path):
    """Scaffold creates flat directory tree (no dpk/puppet/production nesting)."""
    target = tmp_path / "dpk-cust"
    scaffold_dpk_cust_home(target)

    assert (target / "data").is_dir()
    assert (target / "manifests").is_dir()
    assert (target / "modules").is_dir()
    # No nested dpk/ tree
    assert not (target / "dpk").exists()


def test_scaffold_creates_layer_subdirs(tmp_path):
    """Scaffold creates all 5 Hiera layer subdirs including environment/."""
    target = tmp_path / "dpk-cust"
    scaffold_dpk_cust_home(target)

    data = target / "data"
    assert (data / "domain").is_dir()
    assert (data / "server").is_dir()
    assert (data / "environment").is_dir()
    assert (data / "tier").is_dir()
    assert (data / "zone").is_dir()
    # Old env/ dir name should not appear
    assert not (data / "env").exists()


def test_scaffold_creates_readmes(tmp_path):
    """Scaffold writes README files for each layer."""
    target = tmp_path / "dpk-cust"
    scaffold_dpk_cust_home(target)

    assert (target / "README.md").exists()
    assert (target / "data" / "README.md").exists()
    assert (target / "modules" / "README.md").exists()
    for layer in ["domain", "server", "environment", "tier", "zone"]:
        assert (target / "data" / layer / "README.md").exists()


def test_scaffold_creates_common_yaml(tmp_path):
    """Scaffold creates an empty common.yaml stub."""
    target = tmp_path / "dpk-cust"
    scaffold_dpk_cust_home(target)
    assert (target / "data" / "common.yaml").exists()


def test_scaffold_idempotent(tmp_path):
    """Running scaffold twice does not overwrite existing files."""
    target = tmp_path / "dpk-cust"
    scaffold_dpk_cust_home(target)

    readme = target / "README.md"
    readme.write_text("custom content")

    scaffold_dpk_cust_home(target)
    assert readme.read_text() == "custom content"


def test_scaffold_dry_run_creates_nothing(tmp_path):
    """Dry run does not create any files or directories."""
    target = tmp_path / "dpk-cust"
    scaffold_dpk_cust_home(target, dry_run=True)
    assert not target.exists()


# --- psa dpk init command tests ---


def test_init_creates_config_when_missing(tmp_path, monkeypatch):
    """psa dpk init creates ~/.config/psa/config.yaml on first run."""
    config_path = tmp_path / "psa-config.yaml"
    monkeypatch.setattr("psa.commands.dpk.init.CONFIG_PATH", config_path)
    monkeypatch.setattr("psa.core.config.CONFIG_PATH", config_path)

    target = tmp_path / "cust"
    result = runner.invoke(
        dpk_app, ["init", "--path", str(target), "--dpk-path", str(tmp_path / "dpk")]
    )
    assert result.exit_code == 0, result.output
    assert config_path.exists()
    # Hint that user should run config setup next for full path detection
    assert "psa config setup" in result.output.lower()


def test_init_refuses_non_empty_target(tmp_path, monkeypatch):
    """psa dpk init refuses to overwrite a non-empty DPK_CUST_HOME."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")
    monkeypatch.setattr("psa.commands.dpk.init.CONFIG_PATH", config_path)

    target = tmp_path / "cust"
    target.mkdir()
    (target / "existing").write_text("stuff")

    config = PsaConfig()
    with patch("psa.commands.dpk.init.get_config", return_value=config):
        result = runner.invoke(
            dpk_app, ["init", "--path", str(target), "--dpk-path", str(tmp_path / "dpk")]
        )
    assert result.exit_code != 0
    assert "not empty" in result.output.lower()


def test_init_creates_full_scaffold(tmp_path, monkeypatch):
    """psa dpk init creates dirs + hiera.yaml + environment.conf + site.pp."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")
    monkeypatch.setattr("psa.commands.dpk.init.CONFIG_PATH", config_path)

    target = tmp_path / "cust"
    dpk = tmp_path / "dpk"

    config = PsaConfig()
    config.save = lambda p=None: None  # no-op save

    with patch("psa.commands.dpk.init.get_config", return_value=config):
        result = runner.invoke(
            dpk_app, ["init", "--path", str(target), "--dpk-path", str(dpk)]
        )

    assert result.exit_code == 0, result.output
    assert (target / "data").is_dir()
    assert (target / "manifests" / "site.pp").exists()
    assert (target / "modules").is_dir()
    assert (target / "hiera.yaml").exists()
    assert (target / "environment.conf").exists()

    # environment.conf should reference flat modules path + DPK base
    env_content = (target / "environment.conf").read_text()
    assert str(target / "modules") in env_content
    assert str(dpk / "puppet" / "production" / "modules") in env_content
    assert "manifest = manifests/site.pp" in env_content

    # hiera.yaml should reference flat data path
    hiera_content = (target / "hiera.yaml").read_text()
    assert str(target / "data") in hiera_content
    assert "environment/%{facts.env}.yaml" in hiera_content


def test_init_dry_run(tmp_path, monkeypatch):
    """Dry run reports actions but creates no files."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")
    monkeypatch.setattr("psa.commands.dpk.init.CONFIG_PATH", config_path)

    target = tmp_path / "cust"
    config = PsaConfig()

    with patch("psa.commands.dpk.init.get_config", return_value=config):
        result = runner.invoke(
            dpk_app,
            ["init", "--path", str(target), "--dpk-path", str(tmp_path / "dpk"), "--dry-run"],
        )

    assert result.exit_code == 0
    assert not target.exists()
