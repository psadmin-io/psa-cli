"""Tests for psa.core.subprocess_runner."""

import subprocess
from types import SimpleNamespace

import pytest

from psa.core.subprocess_runner import print_stderr_on_failure, stream_subprocess


def test_stream_subprocess_captures_stdout_and_stderr():
    rc, out, err = stream_subprocess(
        ["sh", "-c", "echo hi; echo oops 1>&2; exit 3"]
    )
    assert rc == 3
    assert out.strip() == "hi"
    assert err.strip() == "oops"


def test_stream_subprocess_filter_drops_lines(capsys):
    rc, out, err = stream_subprocess(
        ["sh", "-c", "echo Info: drop; echo Notice: keep"],
        stdout_filter=lambda line: not line.startswith("Info:"),
    )
    captured = capsys.readouterr()
    assert rc == 0
    # both captured even though only one was printed
    assert "Info: drop" in out
    assert "Notice: keep" in out
    # printed stream contains only the kept line
    assert "Notice: keep" in captured.out
    assert "Info: drop" not in captured.out


def test_stream_subprocess_timeout_kills_process():
    with pytest.raises(subprocess.TimeoutExpired):
        stream_subprocess(["sh", "-c", "sleep 5"], timeout=0.2)


def test_print_stderr_on_failure_prints_when_failed(capsys):
    result = SimpleNamespace(returncode=1, stderr="Error: boom\nmore detail\n")
    print_stderr_on_failure(result)
    captured = capsys.readouterr()
    # Goes to stderr via Rich error_console
    assert "Error: boom" in captured.err
    assert "more detail" in captured.err


def test_print_stderr_on_failure_silent_on_success(capsys):
    result = SimpleNamespace(returncode=0, stderr="should not be printed\n")
    print_stderr_on_failure(result)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
