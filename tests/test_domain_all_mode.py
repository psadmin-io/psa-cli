"""Tests for optional domain name (all-mode) behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
import typer

from psa.commands.domain import _confirm_targets, _resolve_targets
from psa.core.config import PsaConfig, OpsConfig
from psa.core.domain import DomainInfo
from psa.core.output import Verbosity, set_verbosity
from psa.core.psadmin import PsadminResult


# --- Fixtures ---


def _make_domain(name, dtype="app"):
    return DomainInfo(
        name=name,
        domain_type=dtype,
        path=Path(f"/fake/{name}"),
        ps_cfg_home=Path("/fake/cfg"),
    )


APPDOM = _make_domain("APPDOM", "app")
PRCSDOM = _make_domain("PRCSDOM", "prcs")
PIADOM = _make_domain("TESTPIA", "pia")
ALL_DOMAINS = [APPDOM, PRCSDOM, PIADOM]


# --- _resolve_targets ---


class TestResolveTargets:
    """Test _resolve_targets helper."""

    @patch("psa.commands.domain._find_domain")
    def test_name_given_returns_single(self, mock_find):
        mock_find.return_value = APPDOM
        result = _resolve_targets("APPDOM", None)
        assert result == [APPDOM]
        mock_find.assert_called_once_with("APPDOM", None)

    @patch("psa.commands.domain._find_domain")
    def test_name_given_not_found_exits(self, mock_find):
        mock_find.return_value = None
        with pytest.raises(click.exceptions.Exit):
            _resolve_targets("NOEXIST", None)

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    def test_name_none_discovers_all(self, mock_disc, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        mock_disc.return_value = ALL_DOMAINS
        result = _resolve_targets(None, None)
        assert result == ALL_DOMAINS

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    def test_name_none_with_type(self, mock_disc, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        mock_disc.return_value = [APPDOM]
        result = _resolve_targets(None, "app")
        assert result == [APPDOM]
        mock_disc.assert_called_once_with(mock_cfg.return_value, "app")

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    def test_skip_types_filters_pia(self, mock_disc, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        mock_disc.return_value = ALL_DOMAINS
        result = _resolve_targets(None, None, skip_types={"pia"})
        assert len(result) == 2
        assert all(d.domain_type != "pia" for d in result)

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    def test_name_none_no_domains_exits(self, mock_disc, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        mock_disc.return_value = []
        with pytest.raises(click.exceptions.Exit):
            _resolve_targets(None, None)

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    def test_skip_types_all_filtered_exits(self, mock_disc, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        mock_disc.return_value = [PIADOM]
        with pytest.raises(click.exceptions.Exit):
            _resolve_targets(None, None, skip_types={"pia"})


# --- _confirm_targets ---


class TestConfirmTargets:
    """Test _confirm_targets helper."""

    def test_single_domain_auto_true(self):
        assert _confirm_targets([APPDOM], "start") is True

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.typer.confirm", return_value=True)
    def test_single_domain_all_mode_prompts(self, mock_confirm, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        result = _confirm_targets([APPDOM], "start", all_mode=True)
        assert result is True
        mock_confirm.assert_called_once()

    def test_quiet_mode_auto_true(self):
        set_verbosity(Verbosity.QUIET)
        try:
            assert _confirm_targets(ALL_DOMAINS, "stop") is True
        finally:
            set_verbosity(Verbosity.DEFAULT)

    @patch("psa.commands.domain.get_config")
    def test_config_skip_auto_true(self, mock_cfg):
        cfg = PsaConfig(skip_domain_confirm=True)
        mock_cfg.return_value = cfg
        assert _confirm_targets(ALL_DOMAINS, "start") is True

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.typer.confirm", return_value=True)
    def test_multi_domain_prompts(self, mock_confirm, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        result = _confirm_targets(ALL_DOMAINS, "stop")
        assert result is True
        mock_confirm.assert_called_once()
        assert "3" in mock_confirm.call_args[0][0]

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.typer.confirm", return_value=False)
    def test_multi_domain_declined(self, mock_confirm, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        result = _confirm_targets(ALL_DOMAINS, "stop")
        assert result is False


# --- Config round-trip ---


class TestSkipDomainConfirmConfig:
    """Test skip_domain_confirm saves and loads."""

    def test_save_load_true(self, tmp_path):
        path = tmp_path / "config.yaml"
        cfg = PsaConfig(skip_domain_confirm=True)
        cfg.save(path)
        loaded = PsaConfig.load(path)
        assert loaded.skip_domain_confirm is True

    def test_default_not_saved(self, tmp_path):
        path = tmp_path / "config.yaml"
        cfg = PsaConfig()
        cfg.save(path)
        loaded = PsaConfig.load(path)
        assert loaded.skip_domain_confirm is False

        # Verify it's not in YAML at all
        content = path.read_text()
        assert "skip_domain_confirm" not in content


# --- Integration: command loops ---


OK_RESULT = PsadminResult(success=True, exit_code=0, output="ok", command="test")
FAIL_RESULT = PsadminResult(success=False, exit_code=1, output="err", command="test")


class TestCommandLoops:
    """Test that commands loop through all domains correctly."""

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_start_loops_all(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import start

        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        start(name=None, serial=False, domain_type=None)

        assert mock_exec.call_count == 2
        # Verify both domains were acted on
        called_domains = [c[0][0].name for c in mock_exec.call_args_list]
        assert "APPDOM" in called_domains
        assert "PRCSDOM" in called_domains

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_stop_loops_all(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import stop

        mock_resolve.return_value = ALL_DOMAINS
        mock_get_ex.return_value = MagicMock()

        stop(name=None, force=False, domain_type=None)

        assert mock_exec.call_count == 3

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_bounce_loops_all(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import bounce

        mock_resolve.return_value = [APPDOM, PIADOM]
        mock_get_ex.return_value = MagicMock()

        bounce(name=None, serial=False, domain_type=None)

        # APPDOM: stop, purge, flush, configure, start = 5
        # PIADOM: stop, purge, start = 3 (no flush/configure for PIA)
        assert mock_exec.call_count == 8

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_configure_skips_pia_in_all_mode(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import configure

        # _resolve_targets would have already filtered PIA via skip_types
        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        configure(name=None, restart=False, serial=False, domain_type=None)

        # 2 domains x (stop + configure) = 4 calls
        assert mock_exec.call_count == 4

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_configure_restart_does_stop_configure_start(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import configure

        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        configure(name=None, restart=True, serial=False, domain_type=None)

        # 2 domains x (stop + configure + start) = 6 calls
        assert mock_exec.call_count == 6

    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_status_no_confirm(self, mock_exec, mock_get_ex, mock_resolve):
        from psa.commands.domain import status

        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        # Should not prompt — no _confirm_targets mock needed
        status(name=None, full=False, json_output=False, domain_type=None, report=False)

        assert mock_exec.call_count == 2

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command")
    def test_failure_summary(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import start

        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()
        mock_exec.side_effect = [OK_RESULT, FAIL_RESULT]

        with pytest.raises(click.exceptions.Exit):
            start(name=None, serial=False, domain_type=None)


ALREADY_STOPPED_RESULT = PsadminResult(success=False, exit_code=1, output="", command="test")
REAL_FAIL_RESULT = PsadminResult(success=False, exit_code=1, output="unexpected error", command="test")


class TestAlreadyStopped:
    """Test that stop/kill on already-stopped domains warn instead of fail."""

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=ALREADY_STOPPED_RESULT)
    def test_stop_already_stopped_warns_not_fails(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import stop

        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        # Should NOT raise — already stopped = warning, exit 0
        stop(name="APPDOM", force=False, domain_type=None)

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=REAL_FAIL_RESULT)
    def test_stop_real_failure_exits(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import stop

        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        with pytest.raises(click.exceptions.Exit):
            stop(name="APPDOM", force=False, domain_type=None)

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=ALREADY_STOPPED_RESULT)
    def test_kill_already_stopped_warns_not_fails(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import kill

        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        # Should NOT raise
        kill(name="APPDOM", domain_type=None)

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command")
    def test_stop_mixed_running_and_stopped(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        """All-mode with mix of running/stopped — no failure count for stopped ones."""
        from psa.commands.domain import stop

        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()
        mock_exec.side_effect = [OK_RESULT, ALREADY_STOPPED_RESULT]

        # Should NOT raise — one stopped + one OK = no failures
        stop(name=None, force=False, domain_type=None)


ALREADY_PURGED_RESULT = PsadminResult(
    success=False, exit_code=1, output="There is no cache to be purged.", command="test"
)


class TestAlreadyPurged:
    """Test that purge on already-purged domains warns instead of fail."""

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=ALREADY_PURGED_RESULT)
    def test_purge_already_purged_warns(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import purge

        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        # Should NOT raise — already purged = warning, exit 0
        purge(name="APPDOM", domain_type=None)

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=REAL_FAIL_RESULT)
    def test_purge_real_failure_fails(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import purge

        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        with pytest.raises(click.exceptions.Exit):
            purge(name="APPDOM", domain_type=None)


class TestSingleDomainNoSummary:
    """Test that single-domain failures skip the ratio summary."""

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=FAIL_RESULT)
    @patch("psa.commands.domain.print_warning")
    def test_single_domain_no_summary(self, mock_warn, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import start

        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        with pytest.raises(click.exceptions.Exit):
            start(name="APPDOM", serial=False, domain_type=None)

        # Should NOT have printed the ratio summary
        for call in mock_warn.call_args_list:
            assert "succeeded" not in str(call), "ratio summary should not appear for single domain"
