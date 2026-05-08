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
    # stderr empty -> exit-code mapping path is exercised. Stderr-with-Error
    # case is covered separately under "Stderr error pattern scan" below.
    result = _run(
        fake_dpk,
        rc=4,
        stdout="Notice: Compiled catalog in 1.2 seconds\n",
        stderr="",
    )
    assert result.exit_code == 1
    assert "resource failures" in result.output


def test_exit_6_changes_plus_failures_exits_nonzero(fake_dpk):
    result = _run(fake_dpk, rc=6, stdout="Notice: Compiled catalog in 1.2 seconds\n")
    assert result.exit_code == 1
    assert "had resource failures" in result.output


def test_exit_1_catalog_error_exits_nonzero(fake_dpk):
    # exit 1 with empty stderr -> exit-code mapping path. The realistic case
    # (exit 1 plus stderr Error:) is covered by the stderr-scan tests below.
    result = _run(fake_dpk, rc=1, stderr="")
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


# --- Auto-sudo for puppet ---


def test_sudo_prepended_when_not_root_or_runtime_user(fake_dpk, monkeypatch):
    """Non-root, non-runtime-user invocation prepends sudo and lifts FACTER_*
    into VAR=val args (sudo strips env by default)."""
    monkeypatch.setenv("USER", "opc")
    monkeypatch.setattr("os.geteuid", lambda: 1000)

    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return 0, "", ""

    dpk, facts_d = fake_dpk
    config = PsaConfig(ops=OpsConfig(), runtime_user="psadm2", sudo_enabled=True)
    with patch("psa.commands.dpk.core.get_config", return_value=config), \
         patch("psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(
            dpk_app, ["apply", "--dpk-home", str(dpk), "--role", "mid"]
        )

    assert result.exit_code == 0
    assert captured["cmd"][0] == "sudo"
    assert "FACTER_ps_role=mid" in captured["cmd"]
    # env should not carry FACTER_* (they live in the cmd args now)
    assert not any(k.startswith("FACTER_") for k in captured["env"])


def test_no_sudo_when_running_as_runtime_user(fake_dpk, monkeypatch):
    monkeypatch.setenv("USER", "psadm2")
    monkeypatch.setattr("os.geteuid", lambda: 1000)

    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return 0, "", ""

    dpk, facts_d = fake_dpk
    config = PsaConfig(ops=OpsConfig(), runtime_user="psadm2", sudo_enabled=True)
    with patch("psa.commands.dpk.core.get_config", return_value=config), \
         patch("psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(
            dpk_app, ["apply", "--dpk-home", str(dpk), "--role", "mid"]
        )

    assert result.exit_code == 0
    assert captured["cmd"][0] != "sudo"
    # FACTER_* should be in env, not cmd
    assert captured["env"].get("FACTER_ps_role") == "mid"


def test_no_sudo_when_already_root(fake_dpk, monkeypatch):
    monkeypatch.setenv("USER", "root")
    monkeypatch.setattr("os.geteuid", lambda: 0)

    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["cmd"] = cmd
        return 0, "", ""

    dpk, facts_d = fake_dpk
    config = PsaConfig(ops=OpsConfig(), sudo_enabled=True)
    with patch("psa.commands.dpk.core.get_config", return_value=config), \
         patch("psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk)])

    assert result.exit_code == 0
    assert captured["cmd"][0] != "sudo"


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


# --- Stderr error pattern scan (overrides apparent success) ---


def test_stderr_error_with_rc_zero_exits_nonzero(fake_dpk):
    """Puppet --noop with --detailed-exitcodes can exit 0 even with catalog
    errors on stderr. The CLI must scan stderr and treat as failure."""
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 0.03 seconds\n",
        stderr=(
            "Warning: Unknown variable: 'env_dpkprereq'\n"
            "Error: Function lookup() did not find a value for the name "
            "'oracle_client_version'\n"
        ),
    )
    assert result.exit_code == 1
    assert "1 error(s) detected on stderr" in result.output


def test_stderr_lookup_pattern_with_rc_two_exits_nonzero(fake_dpk):
    """Even rc=2 (changes-applied success) is overridden by stderr errors."""
    result = _run(
        fake_dpk,
        rc=2,
        stdout="Notice: Compiled catalog in 1.0 seconds\n",
        stderr=(
            "Function lookup() did not find a value for the name 'foo'\n"
        ),
    )
    assert result.exit_code == 1
    assert "detected on stderr" in result.output


def test_stderr_warning_only_does_not_fail(fake_dpk):
    """Warning lines on stderr do not match fatal patterns; success stands."""
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 1.0 seconds\n",
        stderr="Warning: Unknown variable: 'something_optional'\n",
    )
    assert result.exit_code == 0
    assert "no changes needed" in result.output
    assert "detected on stderr" not in result.output


def test_stderr_could_not_find_class_fails(fake_dpk):
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 0.04 seconds\n",
        stderr="Could not find class io_role::io_tools_midtier\n",
    )
    assert result.exit_code == 1
    assert "detected on stderr" in result.output


def test_stderr_evaluation_error_fails(fake_dpk):
    result = _run(
        fake_dpk,
        rc=2,
        stdout="Notice: Compiled catalog in 1.2 seconds\n",
        stderr="Evaluation Error: Operator '[]' is not applicable to undef\n",
    )
    assert result.exit_code == 1


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


# --- Summary mode ---


def _capture_summary_filter(fake_dpk):
    """Run apply --summary; return the stdout_filter passed to stream_subprocess."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["filter"] = kwargs.get("stdout_filter")
        return 0, "Notice: Compiled catalog in 1.0 seconds\n", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk), "--summary"])
    return captured["filter"], result


def test_summary_drops_deprecation_warning(fake_dpk):
    """--summary drops 'is deprecated' Warning lines (and counts them)."""
    f, _ = _capture_summary_filter(fake_dpk)
    assert f is not None
    assert f("Warning: Setting templatedir is deprecated.\n") is False


def test_summary_keeps_errors(fake_dpk):
    """--summary never drops Error: lines."""
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Error: Could not retrieve catalog\n") is True


def test_summary_keeps_stage_state_changes(fake_dpk):
    """Real state-change notices on Stage[] resources are kept (not Notify echoes)."""
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Notice: /Stage[main]/Pt_setup/File[psoft.profile]/ensure: created\n") is True
    assert f("Notice: /Stage[main]/Pt_profile::Pt_system::Users/User[psadm1]/password: changed [redacted] to [redacted]\n") is True
    assert f("Notice: /Stage[main]/Pt_profile::Pt_appserver/Pt_appserver_domain[fscmdv1]/feature_settings: defined 'feature_settings' as ['PUBSUB=Yes']\n") is True


def test_summary_drops_notify_echo_single_line(fake_dpk):
    """The redundant `Notify[...]/message: defined 'message' as ...` echo is dropped."""
    f, _ = _capture_summary_filter(fake_dpk)
    echo = (
        "Notice: /Stage[main]/Pt_profile::Pt_system::Users/Notify[The user psadm1 is present.]"
        "/message: defined 'message' as 'The user psadm1 is present.'\n"
    )
    assert f(echo) is False


def test_summary_drops_notify_echo_multiline_pieces(fake_dpk):
    """Both the opening (`Notice: /Stage[...]/Notify[`) and the continuation
    (`...]/message: defined 'message' as ...`) of multi-line Notify echoes drop."""
    f, _ = _capture_summary_filter(fake_dpk)
    opener = "Notice: /Stage[main]/Pt_profile::Pt_system/Notify[\n"
    closer = "<DPKUSERS>...]/message: defined 'message' as \"\\n<DPKUSERS>...\"\n"
    assert f(opener) is False
    assert f(closer) is False


def test_summary_keeps_dpk_milestone_notices(fake_dpk):
    """`<DPK*>` milestone messages (real progress) are kept."""
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Notice: <DPKAPPDOM> The Application Server domain [fscmdv1] creation is complete.\n") is True
    assert f("Notice: <DPKBOOTPIADOM> The PIA domain [fscmdv1] is running.\n") is True


def test_summary_keeps_compiled_and_applied_catalog(fake_dpk):
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Notice: Compiled catalog in 1.0 seconds\n") is True
    assert f("Notice: Applied catalog in 12.34 seconds\n") is True


def test_summary_drops_scope_notice(fake_dpk):
    """Scope() notices are noise; dropped in --summary."""
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Notice: Scope(Class[main]): something something\n") is False


def test_summary_drops_unknown_variable_warning(fake_dpk):
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Warning: Unknown variable: 'foo'\n") is False


def test_summary_keeps_compilation_warnings(fake_dpk):
    """Generic Warning: lines (not in drop-list) are kept so config issues surface."""
    f, _ = _capture_summary_filter(fake_dpk)
    assert f("Warning: Some compilation issue happened\n") is True


def test_summary_block_printed_when_lines_hidden(fake_dpk):
    """End-of-run summary lists hidden warning/notice counts."""
    stdout = (
        "Notice: Compiled catalog in 1.0 seconds\n"
        "Warning: Setting templatedir is deprecated\n"
        "Warning: Setting confdir is deprecated\n"
        "Notice: Scope(Class[main]): noise\n"
        "Notice: /Stage[main]/Pt_setup/File[x]/ensure: created\n"
    )
    dpk, facts_d = fake_dpk

    def fake_stream(cmd, **kwargs):
        f = kwargs.get("stdout_filter")
        # Drive the filter so its counter is populated.
        if f is not None:
            for line in stdout.splitlines(keepends=True):
                f(line)
        return 0, stdout, ""

    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk), "--summary"])

    assert result.exit_code == 0
    assert "2 warnings hidden" in result.output
    assert "1 notices hidden" in result.output


def test_summary_block_omitted_when_nothing_hidden(fake_dpk):
    """Clean run with no dropped lines should not print a summary block."""
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 1.0 seconds\n",
        extra_args=["--summary"],
    )
    assert result.exit_code == 0
    assert "warnings hidden" not in result.output
    assert "notices hidden" not in result.output


def test_verbose_overrides_summary(fake_dpk):
    """--verbose wins over --summary; stdout_filter is None and a notice prints."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["filter"] = kwargs.get("stdout_filter")
        return 0, "Notice: Compiled catalog in 1.0 seconds\n", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(
            dpk_app,
            ["apply", "--dpk-home", str(dpk), "--summary", "--verbose"],
        )

    assert result.exit_code == 0
    assert captured["filter"] is None
    assert "ignored" in result.output


def test_summary_filters_stderr_too(fake_dpk):
    """Puppet emits Warning/Notice on stderr; --summary must filter stderr too."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["stdout_filter"] = kwargs.get("stdout_filter")
        captured["stderr_filter"] = kwargs.get("stderr_filter")
        return 0, "", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk), "--summary"])

    assert result.exit_code == 0
    assert captured["stdout_filter"] is not None
    assert captured["stderr_filter"] is not None
    # Same callable -> shared counters across both streams.
    assert captured["stdout_filter"] is captured["stderr_filter"]


def test_default_mode_does_not_filter_stderr(fake_dpk):
    """Default mode keeps stderr verbatim (current behavior)."""
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["stderr_filter"] = kwargs.get("stderr_filter")
        return 0, "", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk)])

    assert captured["stderr_filter"] is None


def test_verbose_mode_does_not_filter_stderr(fake_dpk):
    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["stderr_filter"] = kwargs.get("stderr_filter")
        return 0, "", ""

    dpk, facts_d = fake_dpk
    with patch(
        "psa.commands.dpk.core.get_config",
        return_value=PsaConfig(ops=OpsConfig(), sudo_enabled=False),
    ), patch(
        "psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream
    ), patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        runner.invoke(dpk_app, ["apply", "--dpk-home", str(dpk), "--verbose"])

    assert captured["stderr_filter"] is None


def test_summary_handles_ansi_color_codes(fake_dpk):
    """Puppet wraps stderr lines in ANSI color escapes (yellow for Warning).
    The filter must strip ANSI before the prefix test."""
    f, _ = _capture_summary_filter(fake_dpk)
    yellow_warning = (
        "\x1b[1;33mWarning: Unknown variable: 'env_dpkprereq'."
        " (file: /tmp/x.pp, line: 76)\x1b[0m\n"
    )
    assert f(yellow_warning) is False
    yellow_scope = "\x1b[1;33mNotice: Scope(Class[Foo]): bar\x1b[0m\n"
    assert f(yellow_scope) is False
    # Errors still kept, even when wrapped.
    red_error = "\x1b[1;31mError: Could not retrieve catalog\x1b[0m\n"
    assert f(red_error) is True


def test_default_filter_handles_ansi_info_debug(fake_dpk):
    """Default filter (Info/Debug drop) must also handle ANSI-wrapped lines."""
    from psa.commands.dpk.core import _puppet_default_filter
    assert _puppet_default_filter("\x1b[0;36mInfo: chatty\x1b[0m\n") is False
    assert _puppet_default_filter("\x1b[0;37mDebug: noisy\x1b[0m\n") is False
    assert _puppet_default_filter("\x1b[1;33mWarning: keep me\x1b[0m\n") is True


def test_summary_does_not_break_stderr_error_scan(fake_dpk):
    """--summary mode must still escalate fatal stderr errors."""
    result = _run(
        fake_dpk,
        rc=0,
        stdout="Notice: Compiled catalog in 0.03 seconds\n",
        stderr=(
            "Error: Function lookup() did not find a value for the name "
            "'oracle_client_version'\n"
        ),
        extra_args=["--summary"],
    )
    assert result.exit_code == 1
    assert "detected on stderr" in result.output
