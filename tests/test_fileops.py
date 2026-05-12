"""Tests for SudoFileOps."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import subprocess

from psa.core.config import OpsConfig, PsaConfig
from psa.core.fileops import SudoFileOps


@pytest.fixture
def direct_config(tmp_path):
    """Config with sudo disabled — all ops go through pathlib."""
    return PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig(), sudo_enabled=False)


@pytest.fixture
def sudo_config(tmp_path):
    """Config with sudo enabled and USER != runtime_user."""
    return PsaConfig(
        ps_cfg_home=tmp_path,
        ops=OpsConfig(),
        sudo_enabled=True,
        runtime_user="psadm2",
    )


class TestNeedsSudo:
    def test_false_when_disabled(self, direct_config):
        ops = SudoFileOps(direct_config)
        assert ops._needs_sudo() is False

    def test_false_when_user_matches(self, sudo_config):
        ops = SudoFileOps(sudo_config)
        with patch.dict("os.environ", {"USER": "psadm2"}):
            assert ops._needs_sudo() is False

    def test_true_when_user_differs(self, sudo_config):
        ops = SudoFileOps(sudo_config)
        with patch.dict("os.environ", {"USER": "opc"}):
            assert ops._needs_sudo() is True


class TestDirectMode:
    """All ops work via pathlib when sudo_enabled=False."""

    def test_exists_true(self, direct_config, tmp_path):
        (tmp_path / "file.txt").write_text("hi")
        ops = SudoFileOps(direct_config)
        assert ops.exists(tmp_path / "file.txt") is True

    def test_exists_false(self, direct_config, tmp_path):
        ops = SudoFileOps(direct_config)
        assert ops.exists(tmp_path / "nope") is False

    def test_listdir(self, direct_config, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("data")
        ops = SudoFileOps(direct_config)
        entries = ops.listdir(tmp_path)
        names = {name for name, _ in entries}
        assert "subdir" in names
        assert "file.txt" in names
        # Check is_dir flag
        entry_map = dict(entries)
        assert entry_map["subdir"] is True
        assert entry_map["file.txt"] is False

    def test_listdir_empty(self, direct_config, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        ops = SudoFileOps(direct_config)
        assert ops.listdir(empty) == []

    def test_listdir_nonexistent(self, direct_config, tmp_path):
        ops = SudoFileOps(direct_config)
        assert ops.listdir(tmp_path / "nope") == []

    def test_read_text(self, direct_config, tmp_path):
        f = tmp_path / "test.cfg"
        f.write_text("hello world")
        ops = SudoFileOps(direct_config)
        assert ops.read_text(f) == "hello world"

    def test_read_text_missing(self, direct_config, tmp_path):
        ops = SudoFileOps(direct_config)
        assert ops.read_text(tmp_path / "nope") is None

    def test_stat_size(self, direct_config, tmp_path):
        f = tmp_path / "test.cfg"
        f.write_text("12345")
        ops = SudoFileOps(direct_config)
        assert ops.stat_size(f) == 5

    def test_stat_size_missing(self, direct_config, tmp_path):
        ops = SudoFileOps(direct_config)
        assert ops.stat_size(tmp_path / "nope") is None


class TestSudoMode:
    """Verify correct sudo commands are built (mocked subprocess)."""

    def _make_ops(self, sudo_config):
        ops = SudoFileOps(sudo_config)
        return ops

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_exists_calls_test_e(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=0)
        ops = self._make_ops(sudo_config)
        result = ops.exists(Path("/u01/cfg/webserv"))
        assert result is True
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == ["sudo", "su", "-", "psadm2", "-c", "test -e /u01/cfg/webserv"]

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_exists_false_on_nonzero(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=1)
        ops = self._make_ops(sudo_config)
        assert ops.exists(Path("/nope")) is False

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_listdir_parses_ls(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="APPDOM/\nPRCS/\nsome_file\n./\n../\n",
        )
        ops = self._make_ops(sudo_config)
        entries = ops.listdir(Path("/u01/cfg/appserv"))
        assert ("APPDOM", True) in entries
        assert ("PRCS", True) in entries
        assert ("some_file", False) in entries
        # ./ and ../ should be filtered out
        names = [name for name, _ in entries]
        assert "." not in names
        assert ".." not in names

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_listdir_calls_ls(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        ops = self._make_ops(sudo_config)
        ops.listdir(Path("/u01/cfg/appserv"))
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sudo", "su", "-", "psadm2", "-c", "ls -1ap /u01/cfg/appserv"]

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_read_text_calls_cat(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=0, stdout="file content")
        ops = self._make_ops(sudo_config)
        result = ops.read_text(Path("/u01/cfg/psappsrv.cfg"))
        assert result == "file content"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sudo", "su", "-", "psadm2", "-c", "cat /u01/cfg/psappsrv.cfg"]

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_read_text_none_on_failure(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        ops = self._make_ops(sudo_config)
        assert ops.read_text(Path("/nope")) is None

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_stat_size_calls_stat(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=0, stdout="4096\n")
        ops = self._make_ops(sudo_config)
        result = ops.stat_size(Path("/u01/cfg/psappsrv.cfg"))
        assert result == 4096
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sudo", "su", "-", "psadm2", "-c", "stat -c %s /u01/cfg/psappsrv.cfg"]

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_stat_size_none_on_failure(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        ops = self._make_ops(sudo_config)
        assert ops.stat_size(Path("/nope")) is None


class TestWriteTextDirect:
    """write_text without sudo writes via pathlib."""

    def test_writes_file_when_sudo_disabled(self, direct_config, tmp_path):
        ops = SudoFileOps(direct_config)
        target = tmp_path / "sub" / "out.txt"
        assert ops.write_text(target, "hello\n") is True
        assert target.read_text() == "hello\n"

    def test_creates_parent_dirs(self, direct_config, tmp_path):
        ops = SudoFileOps(direct_config)
        target = tmp_path / "a" / "b" / "c.txt"
        assert ops.write_text(target, "x") is True
        assert target.exists()


class TestWriteTextAsRunner:
    """When sudo needed and not as_root, elevate to runtime_user via su."""

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_uses_sudo_su_runtime_user(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=0)
        ops = SudoFileOps(sudo_config)
        ok = ops.write_text(Path("/u01/cfg/file.cfg"), "content\n")
        assert ok is True
        cmd = mock_run.call_args[0][0]
        assert cmd[:5] == ["sudo", "su", "-", "psadm2", "-c"]
        # The shell command should include the path and a base64 pipe
        inner = cmd[5]
        assert "mkdir -p /u01/cfg" in inner
        assert "base64 -d > /u01/cfg/file.cfg" in inner

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_returns_false_on_subprocess_failure(self, mock_run, sudo_config):
        mock_run.return_value = MagicMock(returncode=1)
        ops = SudoFileOps(sudo_config)
        assert ops.write_text(Path("/u01/cfg/file.cfg"), "x") is False

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_last_error_set_on_sudo_failure(self, mock_run, sudo_config):
        """When sudo write fails, last_error captures stderr + exit code for diagnostics."""
        mock_run.return_value = MagicMock(returncode=1, stderr="Permission denied\n")
        ops = SudoFileOps(sudo_config)
        assert ops.write_text(Path("/u01/cfg/file.cfg"), "x") is False
        assert ops.last_error is not None
        assert "exit 1" in ops.last_error
        assert "Permission denied" in ops.last_error

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_last_error_set_on_timeout(self, mock_run, sudo_config):
        """A timeout (typical for password prompt) sets a clear last_error."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sudo", timeout=30)
        ops = SudoFileOps(sudo_config)
        assert ops.write_text(Path("/u01/cfg/file.cfg"), "x") is False
        assert ops.last_error is not None
        assert "passwordless sudo" in ops.last_error

    @patch.dict("os.environ", {"USER": "opc"})
    @patch("psa.core.fileops.subprocess.run")
    def test_last_error_cleared_on_success(self, mock_run, sudo_config):
        """A subsequent successful write clears last_error."""
        mock_run.return_value = MagicMock(returncode=1, stderr="boom\n")
        ops = SudoFileOps(sudo_config)
        ops.write_text(Path("/u01/cfg/a"), "x")
        assert ops.last_error is not None
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        ops.write_text(Path("/u01/cfg/b"), "y")
        assert ops.last_error is None


class TestWriteTextAsRoot:
    """as_root=True falls back to plain sudo bash when direct write fails."""

    @patch("psa.core.fileops.subprocess.run")
    def test_falls_back_to_sudo_bash_on_permission_error(self, mock_run, direct_config):
        """When direct write fails (e.g., root-owned path), retry via sudo bash."""
        mock_run.return_value = MagicMock(returncode=0)
        ops = SudoFileOps(direct_config)
        # /etc/facter/... is not writable by the test user — direct fails, sudo runs.
        ok = ops.write_text(Path("/etc/facter/facts.d/server.yaml"), "ps_role: mid\n", as_root=True)
        assert ok is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["sudo", "bash", "-c"]
        inner = cmd[3]
        assert "mkdir -p /etc/facter/facts.d" in inner
        assert "base64 -d > /etc/facter/facts.d/server.yaml" in inner

    @patch("psa.core.fileops.subprocess.run")
    def test_skips_sudo_when_direct_succeeds(self, mock_run, direct_config, tmp_path):
        """When direct write works (writable tmp path), don't invoke sudo."""
        mock_run.return_value = MagicMock(returncode=0)
        ops = SudoFileOps(direct_config)
        target = tmp_path / "out.yaml"
        ok = ops.write_text(target, "x", as_root=True)
        assert ok is True
        mock_run.assert_not_called()
        assert target.read_text() == "x"

    @patch("psa.core.fileops.subprocess.run")
    def test_base64_encodes_content(self, mock_run, direct_config):
        """Special chars in content survive via base64 over the sudo path."""
        import base64
        mock_run.return_value = MagicMock(returncode=0)
        ops = SudoFileOps(direct_config)
        # Use a path that direct-write can't touch so we hit the sudo branch.
        content = "a: 'quote'\nb: \"double\"\n# comment with `backticks` and $vars\n"
        ops.write_text(Path("/etc/facter/facts.d/x.yaml"), content, as_root=True)
        inner = mock_run.call_args[0][0][3]
        # Extract the base64 chunk between "echo " and " | base64 -d"
        b64 = inner.split("echo ", 1)[1].split(" | ", 1)[0]
        decoded = base64.b64decode(b64).decode("utf-8")
        assert decoded == content
