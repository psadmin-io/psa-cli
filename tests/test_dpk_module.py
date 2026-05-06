"""Tests for psa dpk module install / list."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.commands.dpk.module import (
    REPO_PATTERN,
    _module_info,
    _shorten_remote,
)
from psa.core.config import PsaConfig

runner = CliRunner()


def _ok(stdout="", stderr=""):
    return MagicMock(returncode=0, stdout=stdout, stderr=stderr)


def _fail(stdout="", stderr=""):
    return MagicMock(returncode=1, stdout=stdout, stderr=stderr)


# --- regex / helpers ---


def test_repo_pattern_accepts_valid():
    for r in ["psadmin-io/io_role", "foo/bar", "a.b/c.d", "a_b/c_d"]:
        assert REPO_PATTERN.match(r), r


def test_repo_pattern_rejects_invalid():
    for r in ["nope", "a/b/c", "/x", "x/", "", "../etc/passwd"]:
        assert not REPO_PATTERN.match(r), r


def test_shorten_remote_https():
    assert _shorten_remote("https://github.com/psadmin-io/io_role.git") == "psadmin-io/io_role"


def test_shorten_remote_ssh():
    assert _shorten_remote("git@github.com:psadmin-io/io_role.git") == "psadmin-io/io_role"


def test_shorten_remote_no_dot_git():
    assert _shorten_remote("https://github.com/psadmin-io/io_role") == "psadmin-io/io_role"


def test_shorten_remote_unknown():
    assert _shorten_remote("https://gitlab.example.com/foo/bar.git") == "https://gitlab.example.com/foo/bar.git"


def test_shorten_remote_none():
    assert _shorten_remote(None) is None


# --- _module_info ---


def test_module_info_non_git(tmp_path):
    d = tmp_path / "thing"
    d.mkdir()
    info = _module_info(d)
    assert info == {"name": "thing", "git": False, "remote": None, "branch": None, "commit": None}


def test_module_info_git(tmp_path, monkeypatch):
    d = tmp_path / "io_role"
    (d / ".git").mkdir(parents=True)

    fake_runs = {
        ("remote", "get-url", "origin"): _ok(stdout="https://github.com/psadmin-io/io_role.git\n"),
        ("rev-parse", "--abbrev-ref", "HEAD"): _ok(stdout="main\n"),
        ("rev-parse", "--short", "HEAD"): _ok(stdout="a1b2c3d\n"),
    }

    def fake_git(args, cwd=None, timeout=30):
        return fake_runs[tuple(args)]

    monkeypatch.setattr("psa.commands.dpk.module._git", fake_git)
    info = _module_info(d)
    assert info["git"] is True
    assert info["remote"] == "https://github.com/psadmin-io/io_role.git"
    assert info["branch"] == "main"
    assert info["commit"] == "a1b2c3d"


# --- install command ---


def test_install_clones_module(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    config = PsaConfig()
    fake_clone = MagicMock(return_value=_ok())
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=config):
        result = runner.invoke(
            dpk_app,
            ["module", "install", "psadmin-io/io_role", "--dpk-cust-home", str(tmp_path / "cust")],
        )
    assert result.exit_code == 0, result.output
    fake_clone.assert_called_once()
    call_args = fake_clone.call_args[0][0]
    assert call_args[0] == "clone"
    assert "--depth" in call_args and "1" in call_args
    assert "--branch" in call_args and "main" in call_args
    assert "https://github.com/psadmin-io/io_role.git" in call_args
    # Target path
    expected_target = str(tmp_path / "cust" / "modules" / "io_role")
    assert expected_target in call_args
    assert "1 installed" in result.output


def test_install_branch_override(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    fake_clone = MagicMock(return_value=_ok())
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        runner.invoke(
            dpk_app,
            ["module", "install", "foo/bar", "--branch", "develop", "--dpk-cust-home", str(tmp_path / "c")],
        )
    args = fake_clone.call_args[0][0]
    assert "develop" in args


def test_install_dry_run(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    fake_clone = MagicMock()
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            ["module", "install", "foo/bar", "--dry-run", "--dpk-cust-home", str(tmp_path / "c")],
        )
    assert result.exit_code == 0
    fake_clone.assert_not_called()
    assert "Would clone" in result.output
    assert "1 installed" in result.output


def test_install_skips_existing(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"
    target = cust / "modules" / "io_role"
    target.mkdir(parents=True)
    (target / "existing").write_text("data")

    fake_clone = MagicMock(return_value=_ok())
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            ["module", "install", "psadmin-io/io_role", "--dpk-cust-home", str(cust)],
        )
    assert result.exit_code == 0
    fake_clone.assert_not_called()
    assert "already exists" in result.output
    assert "1 skipped" in result.output


def test_install_invalid_repo_format(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    fake_clone = MagicMock()
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            ["module", "install", "bogus", "--dpk-cust-home", str(tmp_path / "c")],
        )
    assert result.exit_code != 0
    fake_clone.assert_not_called()
    assert "invalid org/repo" in result.output


def test_install_as_overrides_target_dir(tmp_path, monkeypatch):
    """--as <name> overrides the target directory name."""
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    fake_clone = MagicMock(return_value=_ok())
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            [
                "module", "install", "puppetlabs/puppetlabs-inifile",
                "--as", "inifile",
                "--dpk-cust-home", str(tmp_path / "cust"),
            ],
        )
    assert result.exit_code == 0, result.output
    args = fake_clone.call_args[0][0]
    expected_target = str(tmp_path / "cust" / "modules" / "inifile")
    assert expected_target in args
    # Default name (puppetlabs-inifile) should NOT be the target
    default_target = str(tmp_path / "cust" / "modules" / "puppetlabs-inifile")
    assert default_target not in args


def test_install_as_rejects_multiple_repos(tmp_path, monkeypatch):
    """--as with more than one repo is an error."""
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    fake_clone = MagicMock()
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            [
                "module", "install", "foo/a", "foo/b",
                "--as", "shared",
                "--dpk-cust-home", str(tmp_path / "c"),
            ],
        )
    assert result.exit_code != 0
    fake_clone.assert_not_called()
    assert "exactly one repo" in result.output


def test_install_as_rejects_bad_name(tmp_path, monkeypatch):
    """--as rejects names that could escape the modules dir."""
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    fake_clone = MagicMock()
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            [
                "module", "install", "foo/bar",
                "--as", "../etc",
                "--dpk-cust-home", str(tmp_path / "c"),
            ],
        )
    assert result.exit_code != 0
    fake_clone.assert_not_called()
    assert "invalid --as name" in result.output.lower()


def test_install_clone_failure_cleans_up(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"
    fake_clone = MagicMock(return_value=_fail(stderr="not found"))
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            ["module", "install", "ghost/repo", "--dpk-cust-home", str(cust)],
        )
    assert result.exit_code != 0
    assert "1 failed" in result.output


def test_install_multiple_repos_mixed(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"
    # Pre-create one to trigger "already exists"
    (cust / "modules" / "io_role").mkdir(parents=True)
    (cust / "modules" / "io_role" / "f").write_text("x")

    fake_clone = MagicMock(return_value=_ok())
    monkeypatch.setattr("psa.commands.dpk.module._git", fake_clone)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(
            dpk_app,
            [
                "module", "install",
                "psadmin-io/io_role",
                "psadmin-io/io_portalwar",
                "--dpk-cust-home", str(cust),
            ],
        )
    assert result.exit_code == 0
    assert "1 installed" in result.output
    assert "1 skipped" in result.output


# --- list command ---


def test_list_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"
    (cust / "modules").mkdir(parents=True)

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(dpk_app, ["module", "list", "--dpk-cust-home", str(cust)])
    assert result.exit_code == 0
    assert "No modules found" in result.output


def test_list_human(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"
    mod = cust / "modules" / "io_role"
    (mod / ".git").mkdir(parents=True)

    fake_runs = {
        ("remote", "get-url", "origin"): _ok(stdout="https://github.com/psadmin-io/io_role.git\n"),
        ("rev-parse", "--abbrev-ref", "HEAD"): _ok(stdout="main\n"),
        ("rev-parse", "--short", "HEAD"): _ok(stdout="a1b2c3d\n"),
    }
    monkeypatch.setattr(
        "psa.commands.dpk.module._git",
        lambda args, cwd=None, timeout=30: fake_runs[tuple(args)],
    )

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(dpk_app, ["module", "list", "--dpk-cust-home", str(cust)])
    assert result.exit_code == 0
    assert "io_role" in result.output
    assert "psadmin-io/io_role" in result.output


def test_list_json(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"
    mod = cust / "modules" / "io_role"
    (mod / ".git").mkdir(parents=True)
    plain = cust / "modules" / "plain"
    plain.mkdir()

    fake_runs = {
        ("remote", "get-url", "origin"): _ok(stdout="https://github.com/psadmin-io/io_role.git\n"),
        ("rev-parse", "--abbrev-ref", "HEAD"): _ok(stdout="main\n"),
        ("rev-parse", "--short", "HEAD"): _ok(stdout="a1b2c3d\n"),
    }
    monkeypatch.setattr(
        "psa.commands.dpk.module._git",
        lambda args, cwd=None, timeout=30: fake_runs[tuple(args)],
    )

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(dpk_app, ["module", "list", "--dpk-cust-home", str(cust), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["path"].endswith("/modules")
    names = {m["name"] for m in data["modules"]}
    assert names == {"io_role", "plain"}
    io_role = next(m for m in data["modules"] if m["name"] == "io_role")
    assert io_role == {
        "name": "io_role",
        "git": True,
        "remote": "https://github.com/psadmin-io/io_role.git",
        "branch": "main",
        "commit": "a1b2c3d",
    }
    plain_info = next(m for m in data["modules"] if m["name"] == "plain")
    assert plain_info["git"] is False


def test_list_missing_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_CUST_HOME", raising=False)
    cust = tmp_path / "cust"  # not created

    with patch("psa.commands.dpk.module.get_config", return_value=PsaConfig()):
        result = runner.invoke(dpk_app, ["module", "list", "--dpk-cust-home", str(cust), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["modules"] == []
