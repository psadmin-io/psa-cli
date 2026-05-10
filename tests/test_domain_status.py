"""Tests for domain status parsing and command error formatting."""

from pathlib import Path

import pytest

from psa.commands.domain import _format_command_error, _is_already_stopped, _parse_status_output
from psa.core.domain import DomainInfo
from psa.core.psadmin import PsadminResult


def _make_domain(name, dtype="app"):
    return DomainInfo(
        name=name,
        domain_type=dtype,
        path=Path(f"/fake/{name}"),
        ps_cfg_home=Path("/fake/cfg"),
    )


class TestParseStatusOutput:
    """Test _parse_status_output for all domain types."""

    # --- app ---

    def test_app_running_processes(self):
        assert _parse_status_output("3 processes running", "app") == "running"

    def test_app_server_active(self):
        assert _parse_status_output("Server Status: Active", "app") == "running"

    def test_app_not_booted(self):
        assert _parse_status_output("TUXEDO domain not booted", "app") == "stopped"

    def test_app_no_processes(self):
        assert _parse_status_output("No processes found", "app") == "stopped"

    def test_app_is_not_started(self):
        assert _parse_status_output("APPDOM is not started", "app") == "stopped"

    def test_app_tmadmin_table_running(self):
        """tmadmin process table with BBL means domain is booted."""
        output = (
            "> Prog Name      Queue Name  Grp Name      ID\n"
            "---------      ----------  --------      --\n"
            "BBL            200048      vmhost         0\n"
            "PSAPPSRV       APPQ        APPSRV         1\n"
        )
        assert _parse_status_output(output, "app") == "running"

    def test_app_unknown(self):
        assert _parse_status_output("something unexpected", "app") == "unknown"

    # --- prcs ---

    def test_prcs_running(self):
        assert _parse_status_output("Process Scheduler is running", "prcs") == "running"

    def test_prcs_not_running(self):
        assert _parse_status_output("Process Scheduler not running", "prcs") == "stopped"

    def test_prcs_no_process(self):
        assert _parse_status_output("no process found", "prcs") == "stopped"

    def test_prcs_is_not_started(self):
        assert _parse_status_output("PRCSDOM is not started", "prcs") == "stopped"

    def test_prcs_started(self):
        assert _parse_status_output("Started", "prcs") == "running"

    def test_prcs_tmadmin_table_running(self):
        output = (
            "> Prog Name      Queue Name  Grp Name      ID\n"
            "---------      ----------  --------      --\n"
            "BBL            200048      vmhost         0\n"
            "PSPRCSRV       SCHEDQ      PRCS           1\n"
        )
        assert _parse_status_output(output, "prcs") == "running"

    def test_prcs_unknown(self):
        assert _parse_status_output("unexpected output", "prcs") == "unknown"

    # --- web ---

    def test_web_running(self):
        assert _parse_status_output("PIA is running", "web") == "running"

    def test_web_stopped(self):
        assert _parse_status_output("PIA is stopped", "web") == "stopped"

    def test_web_not_running(self):
        assert _parse_status_output("PIA is not running", "web") == "stopped"

    def test_web_unknown(self):
        assert _parse_status_output("unexpected output", "web") == "unknown"


class TestFormatCommandError:
    """Test _format_command_error fallback for empty output."""

    def test_with_output(self):
        result = PsadminResult(success=False, exit_code=1, output="some error text", command="")
        msg = _format_command_error("stop", "APPDOM", result)
        assert msg == "Failed to stop domain: some error text"

    def test_empty_output_stop(self):
        result = PsadminResult(success=False, exit_code=1, output="", command="")
        msg = _format_command_error("stop", "APPDOM", result)
        assert "APPDOM" in msg
        assert "exit code 1" in msg
        assert "already be stopped" in msg

    def test_empty_output_kill(self):
        result = PsadminResult(success=False, exit_code=1, output="  ", command="")
        msg = _format_command_error("kill", "PRCSDOM", result)
        assert "already be stopped" in msg

    def test_empty_output_start(self):
        result = PsadminResult(success=False, exit_code=2, output="", command="")
        msg = _format_command_error("start", "APPDOM", result)
        assert "already be running" in msg
        assert "exit code 2" in msg


class TestIsAlreadyStopped:
    """Test _is_already_stopped helper."""

    def test_success_returns_false(self):
        result = PsadminResult(success=True, exit_code=0, output="ok", command="")
        assert _is_already_stopped(result, _make_domain("APPDOM")) is False

    def test_empty_output_returns_true(self):
        result = PsadminResult(success=False, exit_code=1, output="", command="")
        assert _is_already_stopped(result, _make_domain("APPDOM")) is True

    def test_whitespace_output_returns_true(self):
        result = PsadminResult(success=False, exit_code=1, output="  \n  ", command="")
        assert _is_already_stopped(result, _make_domain("APPDOM")) is True

    def test_stopped_output_returns_true(self):
        result = PsadminResult(success=False, exit_code=1, output="TUXEDO domain not booted", command="")
        assert _is_already_stopped(result, _make_domain("APPDOM")) is True

    def test_real_failure_returns_false(self):
        result = PsadminResult(success=False, exit_code=1, output="unexpected error text", command="")
        assert _is_already_stopped(result, _make_domain("APPDOM")) is False

    def test_web_stopped(self):
        result = PsadminResult(success=False, exit_code=1, output="PIA is not running", command="")
        assert _is_already_stopped(result, _make_domain("TESTWEB", "web")) is True

    def test_prcs_not_started(self):
        result = PsadminResult(success=False, exit_code=1, output="PRCSDOM is not started", command="")
        assert _is_already_stopped(result, _make_domain("PRCSDOM", "prcs")) is True
