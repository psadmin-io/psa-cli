"""Subprocess helpers that surface stderr and respect exit codes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from threading import Thread
from typing import Callable, Mapping, Optional, Tuple

from psa.core.output import print_error


def stream_subprocess(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
    stdout_filter: Optional[Callable[[str], bool]] = None,
    stderr_filter: Optional[Callable[[str], bool]] = None,
) -> Tuple[int, str, str]:
    """Run ``cmd``, streaming output line-by-line while also capturing it.

    - stdout lines are captured; written verbatim to ``sys.stdout`` when
      ``stdout_filter`` is None or returns True for the line.
    - stderr lines are captured; written verbatim to ``sys.stderr`` when
      ``stderr_filter`` is None or returns True for the line. The full
      stderr is always captured in the return value regardless of filter,
      so callers can scan it for fatal patterns.

    Writes go directly to ``sys.stdout``/``sys.stderr`` (not Rich) so output
    is byte-faithful and reliably flushed under multithreaded pumping.

    Returns ``(returncode, full_stdout, full_stderr)``. Raises
    ``subprocess.TimeoutExpired`` after killing the process on timeout.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        bufsize=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stdout_buf: list[str] = []
    stderr_buf: list[str] = []

    def pump_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_buf.append(line)
            if stdout_filter is None or stdout_filter(line):
                sys.stdout.write(line)
                sys.stdout.flush()

    def pump_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_buf.append(line)
            if stderr_filter is None or stderr_filter(line):
                sys.stderr.write(line)
                sys.stderr.flush()

    t_out = Thread(target=pump_stdout, daemon=True)
    t_err = Thread(target=pump_stderr, daemon=True)
    t_out.start()
    t_err.start()

    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        raise

    t_out.join()
    t_err.join()
    return rc, "".join(stdout_buf), "".join(stderr_buf)


def print_stderr_on_failure(
    result: subprocess.CompletedProcess,
    *,
    prefix: str = "",
) -> None:
    """If ``result`` failed and has stderr, print each non-empty line.

    Use after ``subprocess.run(capture_output=True)`` calls that would
    otherwise drop stderr on the floor.
    """
    if result.returncode == 0:
        return
    err = (result.stderr or "").strip()
    if not err:
        return
    for line in err.splitlines():
        if line.strip():
            print_error(f"{prefix}{line}" if prefix else line)
