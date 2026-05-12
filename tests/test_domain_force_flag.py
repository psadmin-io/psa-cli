"""Tests for --force flag on domain commands (skip confirmation prompt)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

from psa.commands.domain import _confirm_targets
from psa.core.config import PsaConfig
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
WEBDOM = _make_domain("TESTWEB", "web")
ALL_DOMAINS = [APPDOM, PRCSDOM, WEBDOM]

OK_RESULT = PsadminResult(success=True, exit_code=0, output="ok", command="test")


# --- _confirm_targets with force ---

class TestConfirmTargetsForce:
    """Test that force=True skips the confirmation prompt."""

    @patch("psa.commands.domain.get_config")
    def test_force_skips_prompt_multi_domain(self, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        assert _confirm_targets(ALL_DOMAINS, "start", force=True) is True

    @patch("psa.commands.domain.get_config")
    def test_force_skips_prompt_all_mode(self, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        assert _confirm_targets([APPDOM], "start", all_mode=True, force=True) is True

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.typer.confirm", return_value=True)
    def test_no_force_still_prompts(self, mock_confirm, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        _confirm_targets(ALL_DOMAINS, "start", force=False)
        mock_confirm.assert_called_once()

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.typer.confirm")
    def test_force_never_calls_confirm(self, mock_confirm, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        _confirm_targets(ALL_DOMAINS, "stop", force=True)
        mock_confirm.assert_not_called()

    @patch("psa.commands.domain.get_config")
    def test_config_skip_and_force_both_work(self, mock_cfg):
        """Both config setting and --force flag skip prompt independently."""
        cfg = PsaConfig(skip_domain_confirm=True)
        mock_cfg.return_value = cfg
        assert _confirm_targets(ALL_DOMAINS, "start", force=True) is True

    @patch("psa.commands.domain.get_config")
    def test_config_skip_without_force(self, mock_cfg):
        cfg = PsaConfig(skip_domain_confirm=True)
        mock_cfg.return_value = cfg
        assert _confirm_targets(ALL_DOMAINS, "start", force=False) is True


# --- Tip text ---

class TestTipText:
    """Test that the tip mentions --force."""

    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.typer.confirm", return_value=True)
    @patch("psa.commands.domain.console")
    def test_tip_mentions_force(self, mock_console, mock_confirm, mock_cfg):
        mock_cfg.return_value = PsaConfig()
        _confirm_targets(ALL_DOMAINS, "start")
        # Find the tip print call
        tip_found = False
        for call in mock_console.print.call_args_list:
            args_str = str(call)
            if "--force" in args_str and "skip_domain_confirm" in args_str:
                tip_found = True
                break
        assert tip_found, "Tip should mention both --force and skip_domain_confirm"


# --- Command integration: --force threads through ---

class TestForceThreading:
    """Test that --force flag is threaded through to _confirm_targets for each command."""

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_start_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import start
        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        start(name=None, serial=False, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_stop_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import stop
        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        stop(name=None, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_bounce_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import bounce
        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        bounce(name=None, serial=False, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_configure_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import configure
        mock_resolve.return_value = [APPDOM, PRCSDOM]
        mock_get_ex.return_value = MagicMock()

        configure(name=None, restart=False, serial=False, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_kill_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import kill
        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        kill(name=None, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_purge_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import purge
        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        purge(name=None, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_flush_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import flush
        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        flush(name=None, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True

    @patch("psa.commands.domain._confirm_targets", return_value=True)
    @patch("psa.commands.domain._resolve_targets")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain._execute_domain_command", return_value=OK_RESULT)
    def test_restart_threads_force(self, mock_exec, mock_get_ex, mock_resolve, mock_confirm):
        from psa.commands.domain import restart
        mock_resolve.return_value = [APPDOM]
        mock_get_ex.return_value = MagicMock()

        restart(name=None, serial=False, domain_type=None, force=True)

        mock_confirm.assert_called_once()
        _, kwargs = mock_confirm.call_args
        assert kwargs.get("force") is True
