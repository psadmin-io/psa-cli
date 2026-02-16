"""Tests for DPK command changes (source path, hiera, modules, puppet.conf)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from psa.commands.dpk.core import (
    _check_dpk_prerequisites,
    _deploy_hiera_files,
    _deploy_module_files,
    _deploy_puppet_conf,
    _generate_hiera_yaml,
    _generate_puppet_conf,
    _get_source_path,
    _verify_puppet,
    DeployType,
)
from psa.core.config import PsaConfig


# --- _get_source_path tests ---


def test_get_source_path_returns_cli_arg(tmp_path):
    """CLI --source arg takes priority."""
    source = tmp_path / "my-source"
    source.mkdir()
    result = _get_source_path(source)
    assert result == source.resolve()


def test_get_source_path_uses_psa_kit_env(monkeypatch, tmp_path):
    """PSA_KIT env var used when no CLI arg."""
    kit = tmp_path / "kit"
    monkeypatch.setenv("PSA_KIT", str(kit))
    result = _get_source_path(None)
    assert result == kit


def test_get_source_path_falls_back_to_config(monkeypatch, tmp_path):
    """Falls back to config.psa_kit_path when env not set."""
    monkeypatch.delenv("PSA_KIT", raising=False)
    config = PsaConfig()
    config.psa_kit_path = tmp_path / "from-config"
    with patch("psa.commands.dpk.core.get_config", return_value=config):
        result = _get_source_path(None)
    assert result == tmp_path / "from-config"


def test_get_source_path_no_io_home(monkeypatch, tmp_path):
    """IO_HOME is no longer checked."""
    monkeypatch.delenv("PSA_KIT", raising=False)
    monkeypatch.setenv("IO_HOME", str(tmp_path / "io-home"))
    config = PsaConfig()
    with patch("psa.commands.dpk.core.get_config", return_value=config):
        result = _get_source_path(None)
    # Should NOT return IO_HOME — falls through to package location
    assert result != tmp_path / "io-home"


# --- _generate_hiera_yaml tests ---


def test_generate_hiera_yaml_with_all_paths(tmp_path):
    """Hiera YAML includes cust, kit, and DPK layers with correct paths."""
    cust = tmp_path / "cust"
    kit = tmp_path / "kit"
    result = _generate_hiera_yaml(cust, kit)

    # Should contain cust datadir
    cust_datadir = str(cust / "dpk" / "puppet" / "production" / "data")
    assert cust_datadir in result

    # Should contain kit datadir
    kit_datadir = str(kit / "dpk" / "puppet" / "production" / "data")
    assert kit_datadir in result

    # Should contain DPK base layers (relative, no datadir)
    assert "psft_configuration.yaml" in result
    assert "psft_customizations.yaml" in result
    assert "defaults.yaml" in result

    # Customer layers should reference correct paths
    assert "domain/%{facts.domainname}.yaml" in result
    assert "server/%{facts.hostname}.yaml" in result
    assert "tier/%{facts.ps_tier}.yaml" in result

    # Kit layer
    assert "psa-ops/common.yaml" in result


def test_generate_hiera_yaml_no_cust():
    """Hiera YAML without cust path skips cust layers."""
    result = _generate_hiera_yaml(None, Path("/kit"))
    assert "domain/" not in result
    assert "server/" not in result
    # Kit layer still present
    assert "psa-ops/common.yaml" in result


def test_generate_hiera_yaml_no_kit():
    """Hiera YAML without kit path skips kit layer."""
    result = _generate_hiera_yaml(Path("/cust"), None)
    assert "psa-ops/common.yaml" not in result
    # Cust layers still present
    assert "domain/%{facts.domainname}.yaml" in result


def test_generate_hiera_yaml_is_valid_yaml(tmp_path):
    """Generated hiera.yaml is valid YAML."""
    result = _generate_hiera_yaml(tmp_path / "cust", tmp_path / "kit")
    parsed = yaml.safe_load(result)
    assert parsed["version"] == 5
    assert "hierarchy" in parsed
    assert isinstance(parsed["hierarchy"], list)


def test_generate_hiera_yaml_dpk_layers_no_datadir(tmp_path):
    """DPK base layers should not have datadir override."""
    result = _generate_hiera_yaml(tmp_path / "cust", tmp_path / "kit")
    # Parse and check DPK layers
    parsed = yaml.safe_load(result)
    dpk_names = [
        "DPK configuration", "DPK customizations", "DPK unix system",
        "DPK deployment", "DPK patches", "DPK defaults",
    ]
    for entry in parsed["hierarchy"]:
        if entry["name"] in dpk_names:
            assert "datadir" not in entry, f"{entry['name']} should not have datadir"


# --- _deploy_hiera_files tests ---


def test_deploy_hiera_files_writes_to_puppet_dirs(dpk_tree, tmp_path):
    """Hiera files deployed to puppet/ and puppet/production/."""
    cust = tmp_path / "cust"
    kit = tmp_path / "kit"
    assert _deploy_hiera_files(dpk_tree, cust, kit, dry_run=False)

    hiera_root = dpk_tree / "puppet" / "hiera.yaml"
    hiera_prod = dpk_tree / "puppet" / "production" / "hiera.yaml"
    assert hiera_root.exists()
    assert hiera_prod.exists()

    content = hiera_root.read_text()
    assert str(cust / "dpk" / "puppet" / "production" / "data") in content


def test_deploy_hiera_files_dry_run(dpk_tree, tmp_path):
    """Dry run does not write files."""
    assert _deploy_hiera_files(dpk_tree, tmp_path / "c", tmp_path / "k", dry_run=True)
    assert not (dpk_tree / "puppet" / "hiera.yaml").exists()


# --- _deploy_module_files tests ---


def test_deploy_module_files_all_io_modules(dpk_tree, kit_source):
    """All io_* modules from source are deployed."""
    result = _deploy_module_files(dpk_tree, kit_source, dry_run=False)
    assert result is True

    modules_dir = dpk_tree / "puppet" / "production" / "modules"
    deployed = sorted(d.name for d in modules_dir.iterdir() if d.is_dir())
    assert "io_profile" in deployed
    assert "io_role" in deployed
    assert "io_tools" in deployed


def test_deploy_module_files_backup_existing(dpk_tree, kit_source):
    """Existing modules are backed up before overwrite."""
    target = dpk_tree / "puppet" / "production" / "modules" / "io_role"
    target.mkdir(parents=True, exist_ok=True)
    (target / "old.pp").write_text("old content")

    _deploy_module_files(dpk_tree, kit_source, dry_run=False)

    backup = dpk_tree / "puppet" / "production" / "modules" / "io_role.bak"
    assert backup.exists()
    assert (backup / "old.pp").exists()


# --- _generate_puppet_conf tests ---


def test_generate_puppet_conf_all_paths(tmp_path):
    """puppet.conf modulepath includes cust:kit:dpk."""
    cust = tmp_path / "cust"
    kit = tmp_path / "kit"
    dpk = tmp_path / "dpk"
    result = _generate_puppet_conf(cust, kit, dpk)

    cust_mod = str(cust / "dpk" / "puppet" / "production" / "modules")
    kit_mod = str(kit / "dpk" / "puppet" / "production" / "modules")
    dpk_mod = str(dpk / "puppet" / "production" / "modules")

    assert cust_mod in result
    assert kit_mod in result
    assert dpk_mod in result

    # Verify order: cust before kit before dpk
    assert result.index(cust_mod) < result.index(kit_mod)
    assert result.index(kit_mod) < result.index(dpk_mod)


def test_generate_puppet_conf_no_cust(tmp_path):
    """puppet.conf without cust only has kit:dpk."""
    kit = tmp_path / "kit"
    dpk = tmp_path / "dpk"
    result = _generate_puppet_conf(None, kit, dpk)

    kit_mod = str(kit / "dpk" / "puppet" / "production" / "modules")
    dpk_mod = str(dpk / "puppet" / "production" / "modules")

    assert kit_mod in result
    assert dpk_mod in result
    assert "cust" not in result


# --- _deploy_puppet_conf tests ---


def test_deploy_puppet_conf_writes_file(dpk_tree, tmp_path):
    """puppet.conf is written to puppet/ directory."""
    assert _deploy_puppet_conf(dpk_tree, tmp_path / "c", tmp_path / "k", dry_run=False)
    target = dpk_tree / "puppet" / "puppet.conf"
    assert target.exists()
    content = target.read_text()
    assert "modulepath" in content


def test_deploy_puppet_conf_dry_run(dpk_tree, tmp_path):
    """Dry run does not write puppet.conf."""
    assert _deploy_puppet_conf(dpk_tree, tmp_path / "c", tmp_path / "k", dry_run=True)
    assert not (dpk_tree / "puppet" / "puppet.conf").exists()


# --- _check_dpk_prerequisites tests ---


def test_prereq_ok_when_libs_exist(tmp_path):
    """No error when all required libs exist."""
    lib = tmp_path / "libncursesw.so.5"
    lib.touch()
    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", [str(lib)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            # Should not raise
            _check_dpk_prerequisites(DeployType.tools_home)


def test_prereq_fix_runs_dnf(tmp_path):
    """--fix auto-installs missing packages via dnf."""
    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", ["/nonexistent/lib.so"]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            mock_run = MagicMock(return_value=MagicMock(returncode=0))
            with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                with patch("os.geteuid", return_value=1000):
                    _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            # Should have called sudo dnf install
            args = mock_run.call_args[0][0]
            assert args[0] == "sudo"
            assert "dnf" in args
            assert "ncurses-compat-libs" in args


def test_prereq_fix_as_root_no_sudo(tmp_path):
    """As root, dnf runs without sudo prefix."""
    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", ["/nonexistent/lib.so"]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            mock_run = MagicMock(return_value=MagicMock(returncode=0))
            with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                with patch("os.geteuid", return_value=0):
                    _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            args = mock_run.call_args[0][0]
            assert args[0] == "dnf"


def test_prereq_prompt_yes_installs(tmp_path):
    """Without --fix, prompts user; 'yes' triggers install."""
    import typer

    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", ["/nonexistent/lib.so"]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            mock_run = MagicMock(return_value=MagicMock(returncode=0))
            with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                with patch("psa.commands.dpk.core.typer.confirm", return_value=True):
                    with patch("os.geteuid", return_value=1000):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=False)
            assert mock_run.called


def test_prereq_prompt_no_exits(tmp_path):
    """Without --fix, declining prompt exits."""
    import pytest
    from click.exceptions import Exit

    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", ["/nonexistent/lib.so"]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core.typer.confirm", return_value=False):
                with patch("os.geteuid", return_value=1000):
                    with pytest.raises(Exit):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=False)


def test_prereq_middleware_checks_libnsl(tmp_path):
    """deploy_type=all checks libnsl and libaio; --fix installs both."""
    ncurses = tmp_path / "libncursesw.so.5"
    ncurses.touch()
    tux_libs = {
        "libaio.so.1": ["/nonexistent/libaio.so.1"],
        "libnsl.so.1": ["/nonexistent/libnsl.so.1"],
    }
    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", [str(ncurses)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", tux_libs):
            mock_run = MagicMock(return_value=MagicMock(returncode=0))
            with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                with patch("os.geteuid", return_value=1000):
                    _check_dpk_prerequisites(DeployType.all, fix=True)
            args = mock_run.call_args[0][0]
            assert "libaio" in args
            assert "libnsl" in args


def test_prereq_middleware_skipped_for_tools_home(tmp_path):
    """deploy_type=tools_home skips middleware lib checks."""
    ncurses = tmp_path / "libncursesw.so.5"
    ncurses.touch()
    tux_libs = {
        "libnsl.so.1": ["/nonexistent/libnsl.so.1"],
    }
    with patch("psa.commands.dpk.core.DPK_REQUIRED_LIBS", [str(ncurses)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", tux_libs):
            # Should not raise — tools_home skips tuxedo libs
            _check_dpk_prerequisites(DeployType.tools_home)


# --- _verify_puppet tests ---


def test_verify_puppet_finds_dpk_puppet(tmp_path, monkeypatch):
    """_verify_puppet finds DPK relocatable Puppet at {base}/psft_puppet_agent/bin/puppet."""
    puppet_bin = tmp_path / "psft_puppet_agent" / "bin" / "puppet"
    puppet_bin.parent.mkdir(parents=True)
    puppet_bin.touch(mode=0o755)

    monkeypatch.setenv("DPK_BASE", str(tmp_path))

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="7.29.1\n"))
    with patch("psa.commands.dpk.core.subprocess.run", mock_run):
        result = _verify_puppet(exit_on_fail=False)

    assert result is True
    mock_run.assert_called_once()
    assert str(puppet_bin) in mock_run.call_args[0][0]


def test_verify_puppet_not_found_no_exit(tmp_path, monkeypatch):
    """_verify_puppet returns False when Puppet binary missing and exit_on_fail=False."""
    monkeypatch.setenv("DPK_BASE", str(tmp_path))

    result = _verify_puppet(exit_on_fail=False)
    assert result is False
