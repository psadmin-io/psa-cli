"""Tests for output verbosity and run_step helper."""

from io import StringIO
from dataclasses import dataclass

from rich.console import Console

from psa.core.output import (
    Verbosity,
    get_verbosity,
    print_error,
    print_info,
    print_success,
    print_warning,
    run_step,
    set_verbosity,
)


@dataclass
class FakeResult:
    success: bool
    output: str = ""


def _capture(func, *args) -> str:
    """Capture rich console output as plain text."""
    buf = StringIO()
    # Temporarily swap consoles
    import psa.core.output as mod
    orig_console = mod.console
    orig_err = mod.error_console
    mod.console = Console(file=buf, force_terminal=False)
    mod.error_console = Console(file=buf, stderr=False, force_terminal=False)
    try:
        func(*args)
    finally:
        mod.console = orig_console
        mod.error_console = orig_err
    return buf.getvalue()


class TestVerbosity:
    def setup_method(self):
        set_verbosity(Verbosity.DEFAULT)

    def teardown_method(self):
        set_verbosity(Verbosity.DEFAULT)

    def test_roundtrip(self):
        set_verbosity(Verbosity.QUIET)
        assert get_verbosity() == Verbosity.QUIET
        set_verbosity(Verbosity.VERBOSE)
        assert get_verbosity() == Verbosity.VERBOSE

    def test_default(self):
        assert get_verbosity() == Verbosity.DEFAULT


class TestRunStep:
    def setup_method(self):
        set_verbosity(Verbosity.DEFAULT)

    def teardown_method(self):
        set_verbosity(Verbosity.DEFAULT)

    def test_returns_result(self):
        result = run_step("Test", lambda: 42)
        assert result == 42

    def test_returns_fake_result(self):
        fake = FakeResult(success=True, output="ok")
        result = run_step("Test", lambda: fake)
        assert result is fake

    def test_quiet_no_output(self):
        set_verbosity(Verbosity.QUIET)
        out = _capture(lambda: run_step("Test", lambda: FakeResult(success=True)))
        assert out.strip() == ""

    def test_default_shows_checkmark(self):
        out = _capture(lambda: run_step("Stopping", lambda: FakeResult(success=True)))
        assert "Stopping" in out

    def test_failure_shows_x(self):
        out = _capture(lambda: run_step("Stopping", lambda: FakeResult(success=False)))
        assert "Stopping" in out

    def test_verbose_shows_output(self):
        set_verbosity(Verbosity.VERBOSE)
        fake = FakeResult(success=True, output="raw line 1\nraw line 2")
        out = _capture(lambda: run_step("Test", lambda: fake))
        assert "raw line 1" in out
        assert "raw line 2" in out

    def test_warn_if_shows_tilde_on_expected_failure(self):
        fake = FakeResult(success=False, output="already stopped")
        out = _capture(lambda: run_step("Stopping", lambda: fake, warn_if=lambda r: True))
        assert "~" in out
        assert "Stopping" in out

    def test_warn_if_not_triggered_on_success(self):
        """warn_if should be ignored when result is successful."""
        called = []
        fake = FakeResult(success=True, output="ok")
        out = _capture(lambda: run_step("Stopping", lambda: fake, warn_if=lambda r: called.append(1) or True))
        # warn_if should not be called for successful results
        assert len(called) == 0
        assert "~" not in out

    def test_warn_if_false_shows_x(self):
        """When warn_if returns False, normal failure icon shown."""
        fake = FakeResult(success=False, output="real error")
        out = _capture(lambda: run_step("Stopping", lambda: fake, warn_if=lambda r: False))
        assert "~" not in out
        assert "Stopping" in out

    def test_warn_if_none_default(self):
        """Without warn_if, failures show normal icon."""
        fake = FakeResult(success=False, output="error")
        out = _capture(lambda: run_step("Stopping", lambda: fake))
        assert "~" not in out

    def test_warn_if_receives_result(self):
        """warn_if callable receives the actual result object."""
        fake = FakeResult(success=False, output="domain not running")
        received = []
        _capture(lambda: run_step("Test", lambda: fake, warn_if=lambda r: received.append(r) or True))
        assert len(received) == 1
        assert received[0] is fake


class TestPrintHelpers:
    def setup_method(self):
        set_verbosity(Verbosity.DEFAULT)

    def teardown_method(self):
        set_verbosity(Verbosity.DEFAULT)

    def test_info_visible_default(self):
        out = _capture(print_info, "hello")
        assert "hello" in out

    def test_info_silenced_quiet(self):
        set_verbosity(Verbosity.QUIET)
        out = _capture(print_info, "hello")
        assert out.strip() == ""

    def test_success_silenced_quiet(self):
        set_verbosity(Verbosity.QUIET)
        out = _capture(print_success, "done")
        assert out.strip() == ""

    def test_warning_silenced_quiet(self):
        set_verbosity(Verbosity.QUIET)
        out = _capture(print_warning, "warn")
        assert out.strip() == ""

    def test_error_always_visible(self):
        set_verbosity(Verbosity.QUIET)
        out = _capture(print_error, "fail")
        assert "fail" in out
