"""Tests for DPK command changes (source path, hiera, modules, environment.conf)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from psa.commands.dpk.core import (
    NCURSES_LIB_NAMES,
    _check_dpk_prerequisites,
    _deploy_environment_conf,
    _deploy_hiera_files,
    _deploy_module_files,
    _detect_os_major_version,
    _generate_environment_conf,
    _generate_hiera_yaml,
    _get_source_path,
    _plan_ncurses_fix,
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
    """Hiera YAML includes cust, kit, and DPK layers with correct paths (kit enabled)."""
    cust = tmp_path / "cust"
    kit = tmp_path / "kit"
    result = _generate_hiera_yaml(cust, kit, enable_psa_kit=True)

    # Should contain cust datadir (flat layout)
    cust_datadir = str(cust / "data")
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
    assert "environment/%{facts.env}.yaml" in result
    # Old env/ directory should not appear (renamed to environment/)
    assert "env/%{facts.env}.yaml" not in result

    # Kit layer (only when enable_psa_kit=True)
    assert "psa-ops/common.yaml" in result


def test_generate_hiera_yaml_kit_disabled_by_default(tmp_path):
    """Default (enable_psa_kit=False) omits kit layer even when kit path is set."""
    result = _generate_hiera_yaml(tmp_path / "cust", tmp_path / "kit")
    assert "psa-ops/common.yaml" not in result
    # Cust layers still present
    assert "domain/%{facts.domainname}.yaml" in result


def test_generate_hiera_yaml_no_cust():
    """Hiera YAML without cust path skips cust layers."""
    result = _generate_hiera_yaml(None, Path("/kit"), enable_psa_kit=True)
    assert "domain/" not in result
    assert "server/" not in result
    # Kit layer still present
    assert "psa-ops/common.yaml" in result


def test_generate_hiera_yaml_no_kit():
    """Hiera YAML without kit path skips kit layer."""
    result = _generate_hiera_yaml(Path("/cust"), None, enable_psa_kit=True)
    assert "psa-ops/common.yaml" not in result
    # Cust layers still present
    assert "domain/%{facts.domainname}.yaml" in result


def test_generate_hiera_yaml_is_valid_yaml(tmp_path):
    """Generated hiera.yaml is valid YAML."""
    result = _generate_hiera_yaml(tmp_path / "cust", tmp_path / "kit", enable_psa_kit=True)
    parsed = yaml.safe_load(result)
    assert parsed["version"] == 5
    assert "hierarchy" in parsed
    assert isinstance(parsed["hierarchy"], list)


def test_generate_hiera_yaml_dpk_layers_no_datadir(tmp_path):
    """DPK base layers should not have datadir override."""
    result = _generate_hiera_yaml(tmp_path / "cust", tmp_path / "kit", enable_psa_kit=True)
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
    # Flat layout: cust datadir is <cust>/data
    assert str(cust / "data") in content


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


# --- _generate_environment_conf tests ---


def test_generate_environment_conf_all_paths(tmp_path):
    """environment.conf modulepath includes cust:kit:dpk when enable_psa_kit=True."""
    cust = tmp_path / "cust"
    kit = tmp_path / "kit"
    dpk = tmp_path / "dpk"
    result = _generate_environment_conf(cust, kit, dpk, enable_psa_kit=True)

    # Flat layout: cust modules is <cust>/modules
    cust_mod = str(cust / "modules")
    kit_mod = str(kit / "dpk" / "puppet" / "production" / "modules")
    dpk_mod = str(dpk / "puppet" / "production" / "modules")

    assert cust_mod in result
    assert kit_mod in result
    assert dpk_mod in result

    # Verify order: cust before kit before dpk
    assert result.index(cust_mod) < result.index(kit_mod)
    assert result.index(kit_mod) < result.index(dpk_mod)

    # Required environment.conf keys
    assert "modulepath" in result
    assert "manifest = manifests/site.pp" in result
    assert "environment_timeout" in result


def test_generate_environment_conf_kit_disabled_by_default(tmp_path):
    """Default (enable_psa_kit=False) omits kit segment from modulepath."""
    cust = tmp_path / "cust"
    kit = tmp_path / "kit"
    dpk = tmp_path / "dpk"
    result = _generate_environment_conf(cust, kit, dpk)

    kit_mod = str(kit / "dpk" / "puppet" / "production" / "modules")
    cust_mod = str(cust / "modules")
    dpk_mod = str(dpk / "puppet" / "production" / "modules")
    assert kit_mod not in result
    assert cust_mod in result
    assert dpk_mod in result


def test_generate_environment_conf_no_cust(tmp_path):
    """environment.conf without cust only has kit:dpk."""
    kit = tmp_path / "kit"
    dpk = tmp_path / "dpk"
    result = _generate_environment_conf(None, kit, dpk, enable_psa_kit=True)

    kit_mod = str(kit / "dpk" / "puppet" / "production" / "modules")
    dpk_mod = str(dpk / "puppet" / "production" / "modules")

    assert kit_mod in result
    assert dpk_mod in result


# --- _deploy_environment_conf tests ---


def test_deploy_environment_conf_writes_file(dpk_tree, tmp_path):
    """environment.conf is written to puppet/production/."""
    assert _deploy_environment_conf(dpk_tree, tmp_path / "c", tmp_path / "k", dry_run=False)
    target = dpk_tree / "puppet" / "production" / "environment.conf"
    assert target.exists()
    content = target.read_text()
    assert "modulepath" in content
    assert "manifest = manifests/site.pp" in content


def test_deploy_environment_conf_dry_run(dpk_tree, tmp_path):
    """Dry run does not write environment.conf."""
    assert _deploy_environment_conf(dpk_tree, tmp_path / "c", tmp_path / "k", dry_run=True)
    assert not (dpk_tree / "puppet" / "production" / "environment.conf").exists()


# --- _check_dpk_prerequisites tests ---


def _touch_all_ncurses(libdir: Path) -> None:
    """Create empty placeholder files for every required ncurses .5 lib."""
    libdir.mkdir(parents=True, exist_ok=True)
    for name in NCURSES_LIB_NAMES:
        (libdir / name).touch()


def _touch_all_ncurses_six(libdir: Path) -> None:
    """Create the corresponding .6 libs (so EL 9 symlinks have a target)."""
    libdir.mkdir(parents=True, exist_ok=True)
    for name in NCURSES_LIB_NAMES:
        (libdir / name.replace(".so.5", ".so.6")).touch()


def test_prereq_ok_when_libs_exist(tmp_path):
    """No error when all required ncurses .5 libs exist."""
    _touch_all_ncurses(tmp_path)
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            _check_dpk_prerequisites(DeployType.tools_home)


def test_prereq_el8_fix_installs_compat_pkg(tmp_path):
    """EL 8: --fix installs ncurses-compat-libs (one shot for all .5 libs)."""
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=8):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=1000):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            args = mock_run.call_args[0][0]
            assert args[0] == "sudo"
            assert "dnf" in args
            assert "ncurses-compat-libs" in args


def test_prereq_unknown_os_falls_back_to_compat_pkg(tmp_path):
    """Unknown OS (no /etc/os-release): falls back to compat-libs install."""
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=None):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=1000):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            args = mock_run.call_args[0][0]
            assert "ncurses-compat-libs" in args


def test_prereq_fix_as_root_no_sudo(tmp_path):
    """As root, dnf runs without sudo prefix."""
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=8):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=0):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            args = mock_run.call_args[0][0]
            assert args[0] == "dnf"


def test_prereq_el9_fix_creates_symlinks_when_six_present(tmp_path):
    """EL 9: when .6 libs exist, --fix runs `ln -s` per missing .5 lib (no dnf)."""
    _touch_all_ncurses_six(tmp_path)
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=9):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=1000):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            # One ln -s per missing .5 lib; no dnf install since .6 already present
            calls = [c.args[0] for c in mock_run.call_args_list]
            assert len(calls) == len(NCURSES_LIB_NAMES)
            for cmd in calls:
                assert cmd[0] == "sudo"
                assert "ln" in cmd
                assert "-s" in cmd
            assert not any("dnf" in cmd for cmd in calls)


def test_prereq_el9_installs_libs_when_six_missing(tmp_path):
    """EL 9: when .6 libs are also missing, install ncurses-libs first then symlink."""
    # Don't create .6 libs — forces the dnf install step
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=9):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=1000):
                        _check_dpk_prerequisites(DeployType.tools_home, fix=True)
            calls = [c.args[0] for c in mock_run.call_args_list]
            # First call = dnf install ncurses-libs
            assert "ncurses-libs" in calls[0]
            assert "dnf" in calls[0]
            # Subsequent calls = ln -s per lib
            for cmd in calls[1:]:
                assert "ln" in cmd


def test_prereq_el9_recommend_lists_symlinks(tmp_path):
    """EL 9: plan output includes per-lib symlink commands (no compat-libs)."""
    _touch_all_ncurses_six(tmp_path)
    actions = _plan_ncurses_fix(NCURSES_LIB_NAMES, os_major=9)
    # No dnf install needed since .6 libs exist (but _plan_ncurses_fix doesn't see tmp_path
    # without LIB_SEARCH_DIRS patch — so test the patched flow):
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        actions = _plan_ncurses_fix(NCURSES_LIB_NAMES, os_major=9)
    assert len(actions) == len(NCURSES_LIB_NAMES)
    for action in actions:
        assert "ln" in action.command
        assert "-s" in action.command
    assert not any("ncurses-compat-libs" in a.command for a in actions)


def test_prereq_idempotent_when_already_fixed(tmp_path):
    """Re-running with all libs present (post-fix) is silent and exits 0."""
    _touch_all_ncurses(tmp_path)
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=9):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    _check_dpk_prerequisites(DeployType.tools_home, fix=True)
                assert not mock_run.called


def test_prereq_symlink_failure_raises(tmp_path):
    """If `ln -s` fails, surface a clear error and exit non-zero."""
    import pytest
    from click.exceptions import Exit

    _touch_all_ncurses_six(tmp_path)
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=9):
                mock_run = MagicMock(return_value=MagicMock(returncode=1))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=1000):
                        with pytest.raises(Exit):
                            _check_dpk_prerequisites(DeployType.tools_home, fix=True)


def test_prereq_prompt_yes_installs(tmp_path):
    """Without --fix, prompts user; 'yes' triggers install."""
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=8):
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

    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", {}):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=8):
                with patch("psa.commands.dpk.core.typer.confirm", return_value=False):
                    with patch("os.geteuid", return_value=1000):
                        with pytest.raises(Exit):
                            _check_dpk_prerequisites(DeployType.tools_home, fix=False)


def test_prereq_middleware_checks_libnsl(tmp_path):
    """deploy_type=all checks libnsl and libaio; --fix installs both."""
    _touch_all_ncurses(tmp_path)
    tux_libs = {
        "libaio.so.1": ["/nonexistent/libaio.so.1"],
        "libnsl.so.1": ["/nonexistent/libnsl.so.1"],
    }
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", tux_libs):
            with patch("psa.commands.dpk.core._detect_os_major_version", return_value=8):
                mock_run = MagicMock(return_value=MagicMock(returncode=0))
                with patch("psa.commands.dpk.core.subprocess.run", mock_run):
                    with patch("os.geteuid", return_value=1000):
                        _check_dpk_prerequisites(DeployType.all, fix=True)
            args = mock_run.call_args[0][0]
            assert "libaio" in args
            assert "libnsl" in args


def test_prereq_middleware_skipped_for_tools_home(tmp_path):
    """deploy_type=tools_home skips middleware lib checks."""
    _touch_all_ncurses(tmp_path)
    tux_libs = {
        "libnsl.so.1": ["/nonexistent/libnsl.so.1"],
    }
    with patch("psa.commands.dpk.core.LIB_SEARCH_DIRS", [str(tmp_path)]):
        with patch("psa.commands.dpk.core.TUXEDO_REQUIRED_LIBS", tux_libs):
            _check_dpk_prerequisites(DeployType.tools_home)


# --- _detect_os_major_version tests ---


def test_detect_os_version_parses_quoted_value(tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text('NAME="Oracle Linux Server"\nVERSION_ID="9.4"\nID="ol"\n')
    with patch("psa.commands.dpk.core.OS_RELEASE_PATH", str(osr)):
        assert _detect_os_major_version() == 9


def test_detect_os_version_parses_unquoted(tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text("VERSION_ID=8\n")
    with patch("psa.commands.dpk.core.OS_RELEASE_PATH", str(osr)):
        assert _detect_os_major_version() == 8


def test_detect_os_version_missing_file_returns_none(tmp_path):
    with patch("psa.commands.dpk.core.OS_RELEASE_PATH", str(tmp_path / "nope")):
        assert _detect_os_major_version() is None


def test_detect_os_version_no_version_id_returns_none(tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text('NAME="Some OS"\n')
    with patch("psa.commands.dpk.core.OS_RELEASE_PATH", str(osr)):
        assert _detect_os_major_version() is None


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
