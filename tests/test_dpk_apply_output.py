"""Tests for psa dpk apply error handling, exit-code mapping, and diagnostics."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


@pytest.fixture
def fake_dpk(tmp_path):
    """Minimal DPK tree mirroring the fixture in test_dpk_apply_facts."""
    dpk = tmp_path / "psft"
    puppet_dir = dpk / "puppet"
    (puppet_dir / "production" / "manifests").mkdir(parents=True)
    (puppet_dir / "production" / "manifests" / "site.pp").write_text("# site")
    puppet_bin = tmp_path / "psft_puppet_agent" / "bin" / "puppet"
    puppet_bin.parent.mkdir(parents=True)
    puppet_bin.write_text("#!/bin/sh\nexit 0\n")
    puppet_bin.chmod(0o755)
    facts_d = tmp_path / "etc-puppetlabs-facts.d"
    facts_d.mkdir()
    return dpk, facts_d


def _run(fake_dpk, *, rc=0, stdout="", stderr="", extra_args=None, config=None):
    """Run apply with stream_subprocess returning the given (rc, stdout, stderr)."""
    dpk, facts_d = fake_dpk
    if config is None:
        config = PsaConfig(ops=OpsConfig(), sudo_enabled=False)

    def fake_stream(cmd, **kwargs):
        return rc, stdout, stderr

    args = ["apply", "--dpk-home", str(dpk)] + (extra_args or [])
    with patch("psa.commands.dpk.core.get_config", return_value=config), \
         patch("psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        return runner.invoke(dpk_app, args)


# --- Exit code mapping ---


def test_exit_0_reports_no_changes(fake_dpk):
    result = _run(fake_dpk, rc=0, stdout="Notice: Compiled catalog in 1.2 seconds\n")
    assert result.exit_code == 0
    assert "no changes needed" in result.output


def test_exit_2_dry_run_reports_would_change(fake_dpk):
    result = _run(
        fake_dpk,
        rc=2,
        stdout="Notice: Compiled catalog in 1.2 seconds\n",
        extra_args=["--dry-run"],
    )
    assert result.exit_code == 0
    assert "would make changes" in result.output


def test_exit_2_real_apply_reports_changes_applied(fake_dpk):
    result = _run(fake_dpk, rc=2, stdout="Notice: Compiled catalog in 1.2 seconds\n")
    assert result.exit_code == 0
    assert "changes applied" in result.output


def test_exit_4_resource_failure_exits_nonzero(fake_dpk):
    result = _run(
        fake_dpk,
        rc=4,
        stdout="Notice: Compiled catalog in 1.2 seconds\n",
        stderr="Error: /Stage[main]/...: change from absent to present failed\n",
    )
    assert result.exit_code == 1
    assert "resource failures" in result.output


def test_exit_6_changes_plus_failures_exits_nonzero(fake_dpk):
    result = _run(fake_dpk, rc=6, stdout="Notice: Compiled catalog in 1.2 seconds\n")
    assert result.exit_code == 1
    assert "had resource failures" in result.output


def test_exit_1_catalog_error_exits_nonzero(fake_dpk):
    result = _run(
        fake_dpk,
        rc=1,
        stderr=(
            "Error: Function lookup() did not find a value "
            "for the name 'oracle_client_version'\n"
        ),
    )
    assert result.exit_code == 1
    assert "catalog compilation" in result.output


# --- Diagnostics ---


def test_fast_compile_emits_warning(fake_dpk):
    result = _run(
        fake_dpk,
        rc=0,
        stdout=(
            "Notice: Compiled catalog for midtier in environment production "
            "in 0.03 seconds\n"
        ),
    )
    assert result.exit_code == 0
    assert "unusually fast" in result.output


def test_normal_compile_no_warning(fake_dpk):
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 1.2 seconds\n",
    )
    assert "unusually fast" not in result.output


def test_change_count_is_reported(fake_dpk):
    stdout = (
        "Notice: Compiled catalog in 2.1 seconds\n"
        "Notice: /Stage[main]/Foo/File[/etc/foo]/ensure: created\n"
        "Notice: /Stage[main]/Bar/Service[bar]/ensure: ensure changed\n"
        "Notice: Applied catalog in 0.5 seconds\n"
    )
    result = _run(fake_dpk, rc=2, stdout=stdout)
    assert result.exit_code == 0
    assert "Changed: 2 resources" in result.output


def test_change_count_dry_run_uses_would_change(fake_dpk):
    stdout = (
        "Notice: Compiled catalog in 2.1 seconds\n"
        "Notice: /Stage[main]/Foo/File[/etc/foo]/ensure: current_value absent\n"
    )
    result = _run(fake_dpk, rc=2, stdout=stdout, extra_args=["--dry-run"])
    assert result.exit_code == 0
    assert "Would change: 1 resources" in result.output


# --- Role resolution ---


def test_role_resolution_prints_class(fake_dpk):
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 1.0 seconds\n",
        extra_args=["--role", "mid"],
    )
    assert "Resolved ps_role=mid -> io_role::io_tools_midtier" in result.output


def test_unknown_role_warns(fake_dpk):
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 1.0 seconds\n",
        extra_args=["--role", "bogus"],
    )
    assert "does not match any class" in result.output


def test_no_role_anywhere_warns(fake_dpk):
    result = _run(fake_dpk, rc=0, stdout="Notice: Compiled catalog in 1.0 seconds\n")
    assert "ps_role is not set" in result.output


# --- Verbose flag ---


def test_detailed_exitcodes_always_passed(fake_dpk):
    """The fix relies on --detailed-exitcodes being on the puppet command."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["cmd"] = cmd
        return 0, "", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk)])

    assert result.exit_code == 0
    assert "--detailed-exitcodes" in captured["cmd"]


def test_verbose_disables_stdout_filter(fake_dpk):
    """With --verbose, stream_subprocess gets stdout_filter=None."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["filter"] = kwargs.get("stdout_filter")
        return 0, "", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk), "--verbose"])

    assert result.exit_code == 0
    assert captured["filter"] is None


def test_default_filter_drops_info_and_debug(fake_dpk):
    """Without --verbose, the supplied filter rejects Info: and Debug:."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["filter"] = kwargs.get("stdout_filter")
        return 0, "", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk)])

    f = captured["filter"]
    assert f is not None
    assert f("Notice: Compiled catalog in 1.0 seconds\n") is True
    assert f("Warning: foo\n") is True
    assert f("Error: bar\n") is True
    assert f("Info: chatty\n") is False
    assert f("Debug: noisy\n") is False
    assert f("  Info: indented\n") is False
