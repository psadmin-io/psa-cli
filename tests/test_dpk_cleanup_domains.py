"""Tests for `psa dpk cleanup --domains-only`."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.commands.dpk.core import _cleanup_domains_only, _sudo_rm_rf
from psa.core import dpk_services
from psa.core.domain import DomainInfo
from psa.core.psadmin import PsadminExecutor, PsadminResult

runner = CliRunner()


# --- Fixtures ---


def _domain(name, dtype, path=None):
    return DomainInfo(
        name=name,
        domain_type=dtype,
        path=path or Path(f"/fake/{dtype}/{name}"),
        ps_cfg_home=Path("/fake/cfg"),
    )


OK = PsadminResult(success=True, exit_code=0, output="ok", command="test")
FAIL_RUNNING = PsadminResult(success=False, exit_code=1, output="processes running", command="x")


# --- Executor delete methods ---


class TestExecutorDeleteMethods:
    """psadmin -c/-p/-w delete wrappers pipe 'y' to handle interactive prompt."""

    @patch("psa.core.psadmin.subprocess.run")
    def test_app_delete_passes_y_stdin(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ex = PsadminExecutor()
        ex.app_delete("APPDOM")
        # subprocess.run is called once; check input was piped
        args, kwargs = mock_run.call_args
        assert kwargs.get("input", "").startswith("y")
        # And the psadmin args end with the delete action
        cmd = args[0]
        joined = " ".join(cmd) if isinstance(cmd, list) else cmd
        assert "-c" in joined
        assert "delete" in joined
        assert "APPDOM" in joined

    @patch("psa.core.psadmin.subprocess.run")
    def test_prcs_delete_uses_p_flag(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        PsadminExecutor().prcs_delete("PRCSDOM")
        cmd = mock_run.call_args.args[0]
        joined = " ".join(cmd)
        assert "-p" in joined and "delete" in joined and "PRCSDOM" in joined

    @patch("psa.core.psadmin.subprocess.run")
    def test_web_delete_uses_w_flag(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        PsadminExecutor().web_delete("WEBDOM")
        cmd = mock_run.call_args.args[0]
        joined = " ".join(cmd)
        assert "-w" in joined and "delete" in joined and "WEBDOM" in joined


# --- dpk_services ---


class TestDpkServices:
    """unit_name, find_unit_paths, remove_unit basics."""

    def test_unit_name_app(self):
        assert dpk_services.unit_name("app", "ihlab") == "psft-appserver-ihlab"

    def test_unit_name_prcs(self):
        assert dpk_services.unit_name("prcs", "ihlab") == "psft-prcs-ihlab"

    def test_unit_name_web(self):
        assert dpk_services.unit_name("web", "ihlab") == "psft-pia-ihlab"

    def test_unit_name_unknown_type_raises(self):
        with pytest.raises(ValueError):
            dpk_services.unit_name("bogus", "x")

    def test_find_unit_paths_appends_service_suffix(self, tmp_path, monkeypatch):
        unit_dir = tmp_path / "systemd"
        unit_dir.mkdir()
        (unit_dir / "psft-pia-ihlab.service").write_text("[Unit]\n")
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [unit_dir])
        paths = dpk_services.find_unit_paths("psft-pia-ihlab")
        assert paths == [unit_dir / "psft-pia-ihlab.service"]

    def test_find_unit_paths_accepts_full_suffix(self, tmp_path, monkeypatch):
        unit_dir = tmp_path / "systemd"
        unit_dir.mkdir()
        (unit_dir / "psft-pia-ihlab.service").write_text("[Unit]\n")
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [unit_dir])
        paths = dpk_services.find_unit_paths("psft-pia-ihlab.service")
        assert len(paths) == 1

    def test_find_unit_paths_returns_empty_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [tmp_path / "nope"])
        assert dpk_services.find_unit_paths("psft-pia-ihlab") == []

    def test_find_unit_paths_returns_symlinks_even_when_target_missing(
        self, tmp_path, monkeypatch
    ):
        unit_dir = tmp_path / "wants"
        unit_dir.mkdir()
        link = unit_dir / "psft-pia-ihlab.service"
        link.symlink_to(tmp_path / "does-not-exist")
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [unit_dir])
        assert dpk_services.find_unit_paths("psft-pia-ihlab") == [link]

    def test_remove_unit_dry_run_does_not_invoke_subprocess(
        self, tmp_path, monkeypatch
    ):
        unit_dir = tmp_path / "systemd"
        unit_dir.mkdir()
        unit_file = unit_dir / "psft-pia-ihlab.service"
        unit_file.write_text("[Unit]\n")
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [unit_dir])
        with patch("psa.core.dpk_services._run") as mock_run:
            r = dpk_services.remove_unit("web", "ihlab", dry_run=True)
        mock_run.assert_not_called()
        assert r.success is True
        assert unit_file.exists()
        assert "would remove" in r.output

    def test_remove_unit_missing_is_success_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [tmp_path / "empty"])
        r = dpk_services.remove_unit("app", "absent")
        assert r.success is True
        assert "No DPK service unit" in r.output

    def test_remove_unit_runs_stop_disable_rm(self, tmp_path, monkeypatch):
        unit_dir = tmp_path / "systemd"
        unit_dir.mkdir()
        unit_file = unit_dir / "psft-appserver-ihlab.service"
        unit_file.write_text("[Unit]\n")
        monkeypatch.setattr(dpk_services, "UNIT_SEARCH_DIRS", [unit_dir])

        calls = []

        def fake_run(cmd, timeout=30):
            calls.append(cmd)
            if cmd[-2:] == ["rm", "-f"] or "rm" in cmd:
                # Actually remove on rm call to mirror real behavior
                if cmd[-1] == str(unit_file):
                    unit_file.unlink()
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(dpk_services, "_run", fake_run)
        # Force non-root path so sudo is prepended (matches typical usage)
        monkeypatch.setattr(dpk_services.os, "geteuid", lambda: 1000)

        r = dpk_services.remove_unit("app", "ihlab")
        assert r.success is True
        # Verify stop, disable, rm were all attempted (sudo-wrapped)
        action_words = [" ".join(c) for c in calls]
        assert any("systemctl stop psft-appserver-ihlab.service" in s for s in action_words)
        assert any("systemctl disable psft-appserver-ihlab.service" in s for s in action_words)
        assert any(f"rm -f {unit_file}" in s for s in action_words)


# --- Flag dispatch / validation ---


class TestCleanupFlagDispatch:
    """`psa dpk cleanup` flag wiring & validation."""

    def test_scoping_flags_without_domains_only_errors(self):
        result = runner.invoke(dpk_app, ["cleanup", "--domain", "APPDOM"])
        assert result.exit_code == 2
        assert "--domains-only" in result.output

    def test_keep_services_without_domains_only_errors(self):
        result = runner.invoke(dpk_app, ["cleanup", "--keep-services"])
        assert result.exit_code == 2

    def test_type_without_domains_only_errors(self):
        result = runner.invoke(dpk_app, ["cleanup", "--type", "app"])
        assert result.exit_code == 2

    @patch("psa.commands.dpk.core._cleanup_domains_only")
    def test_domains_only_dispatches_to_helper(self, mock_helper):
        result = runner.invoke(
            dpk_app, ["cleanup", "--domains-only", "--dry-run", "--force"]
        )
        assert result.exit_code == 0
        mock_helper.assert_called_once()
        kwargs = mock_helper.call_args.kwargs
        assert kwargs["dry_run"] is True
        assert kwargs["force"] is True
        assert kwargs["keep_services"] is False
        assert kwargs["domain"] is None
        assert kwargs["domain_type"] is None

    @patch("psa.commands.dpk.core._cleanup_domains_only")
    def test_domains_only_passes_scoping_args(self, mock_helper):
        runner.invoke(
            dpk_app,
            [
                "cleanup",
                "--domains-only",
                "--domain",
                "APPDOM",
                "--type",
                "app",
                "--keep-services",
            ],
        )
        kwargs = mock_helper.call_args.kwargs
        assert kwargs["domain"] == "APPDOM"
        assert kwargs["domain_type"] == "app"
        assert kwargs["keep_services"] is True

    @patch("psa.commands.dpk.core._cleanup_domains_only")
    @patch("psa.commands.dpk.core.stream_subprocess")
    def test_legacy_path_still_works(self, mock_stream, mock_helper):
        """Without --domains-only, dispatches to the legacy full-cleanup path."""
        mock_stream.return_value = (0, "", "")
        # Will fail on missing setup script — that's fine, we only want to verify
        # the new helper isn't called.
        runner.invoke(
            dpk_app,
            ["cleanup", "--base-dir", "/nonexistent", "--install-dir", "/nonexistent"],
        )
        mock_helper.assert_not_called()


# --- _cleanup_domains_only orchestration ---


class TestCleanupOrchestration:
    """End-to-end behavior of _cleanup_domains_only (with mocks)."""

    @patch("psa.commands.dpk.core.PsadminExecutor")
    @patch("psa.commands.dpk.core.SudoFileOps")
    @patch("psa.commands.dpk.core.run_discovery")
    @patch("psa.commands.dpk.core.dpk_services.remove_unit")
    @patch("psa.commands.dpk.core.dpk_services.daemon_reload")
    @patch("psa.commands.dpk.core._sudo_rm_rf")
    def test_per_domain_calls_stop_delete_service(
        self, mock_rm, mock_reload, mock_remove_unit, mock_discover, mock_fileops_cls, mock_exec_cls
    ):
        mock_discover.return_value = [_domain("APPDOM", "app")]
        # fileops.exists returns False so rm-fallback is skipped
        fileops = MagicMock()
        fileops.exists.return_value = False
        mock_fileops_cls.return_value = fileops
        mock_remove_unit.return_value = dpk_services.ServiceOpResult(success=True, output="ok")
        mock_reload.return_value = dpk_services.ServiceOpResult(success=True, output="ok")

        # Mock executor + method_map dispatch indirectly via _execute_domain_command
        with patch("psa.commands.domain._execute_domain_command", return_value=OK):
            _cleanup_domains_only(
                domain=None, domain_type=None, keep_services=False, force=True, dry_run=False
            )

        # rm-fallback not used (dir doesn't exist)
        mock_rm.assert_not_called()
        # Service unit removed exactly once for the single domain
        mock_remove_unit.assert_called_once_with("app", "APPDOM")
        # daemon-reload called once at the end
        mock_reload.assert_called_once()

    @patch("psa.commands.dpk.core.PsadminExecutor")
    @patch("psa.commands.dpk.core.SudoFileOps")
    @patch("psa.commands.dpk.core.run_discovery")
    @patch("psa.commands.dpk.core.dpk_services.remove_unit")
    @patch("psa.commands.dpk.core.dpk_services.daemon_reload")
    def test_keep_services_skips_unit_removal_and_reload(
        self, mock_reload, mock_remove_unit, mock_discover, mock_fileops_cls, mock_exec_cls
    ):
        mock_discover.return_value = [_domain("APPDOM", "app")]
        fileops = MagicMock()
        fileops.exists.return_value = False
        mock_fileops_cls.return_value = fileops

        with patch("psa.commands.domain._execute_domain_command", return_value=OK):
            _cleanup_domains_only(
                domain=None, domain_type=None, keep_services=True, force=True, dry_run=False
            )

        mock_remove_unit.assert_not_called()
        mock_reload.assert_not_called()

    @patch("psa.commands.dpk.core.run_discovery")
    @patch("psa.commands.dpk.core.dpk_services.remove_unit")
    def test_dry_run_does_not_execute(self, mock_remove_unit, mock_discover):
        mock_discover.return_value = [_domain("APPDOM", "app")]
        with patch("psa.commands.domain._execute_domain_command") as mock_exec:
            _cleanup_domains_only(
                domain=None, domain_type=None, keep_services=False, force=True, dry_run=True
            )
        # Neither the executor nor systemctl-side is invoked
        mock_exec.assert_not_called()
        mock_remove_unit.assert_not_called()

    @patch("psa.commands.dpk.core.run_discovery")
    def test_no_domains_exits_nonzero(self, mock_discover):
        mock_discover.return_value = []
        import typer as _typer
        with pytest.raises(_typer.Exit):
            _cleanup_domains_only(
                domain=None, domain_type=None, keep_services=False, force=True, dry_run=False
            )

    @patch("psa.commands.dpk.core.PsadminExecutor")
    @patch("psa.commands.dpk.core.SudoFileOps")
    @patch("psa.commands.dpk.core.run_discovery")
    @patch("psa.commands.dpk.core.dpk_services.remove_unit")
    @patch("psa.commands.dpk.core.dpk_services.daemon_reload")
    @patch("psa.commands.dpk.core._sudo_rm_rf")
    def test_rm_fallback_when_domain_dir_remains(
        self, mock_rm, mock_reload, mock_remove_unit, mock_discover, mock_fileops_cls, mock_exec_cls
    ):
        mock_discover.return_value = [_domain("APPDOM", "app")]
        fileops = MagicMock()
        fileops.exists.return_value = True  # dir still present after psadmin delete
        mock_fileops_cls.return_value = fileops
        mock_rm.return_value = PsadminResult(success=True, exit_code=0, output="ok", command="rm")
        mock_remove_unit.return_value = dpk_services.ServiceOpResult(success=True, output="ok")
        mock_reload.return_value = dpk_services.ServiceOpResult(success=True, output="ok")

        with patch("psa.commands.domain._execute_domain_command", return_value=OK):
            _cleanup_domains_only(
                domain=None, domain_type=None, keep_services=False, force=True, dry_run=False
            )

        mock_rm.assert_called_once()


# --- _sudo_rm_rf ---


class TestSudoRmRf:
    @patch("psa.commands.dpk.core.subprocess.run")
    def test_uses_sudo_when_non_root(self, mock_run, monkeypatch):
        monkeypatch.setattr("psa.commands.dpk.core.os.geteuid", lambda: 1000)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = _sudo_rm_rf(Path("/some/dir"))
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "sudo"
        assert cmd[1:] == ["rm", "-rf", "/some/dir"]
        assert r.success is True

    @patch("psa.commands.dpk.core.subprocess.run")
    def test_no_sudo_when_root(self, mock_run, monkeypatch):
        monkeypatch.setattr("psa.commands.dpk.core.os.geteuid", lambda: 0)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _sudo_rm_rf(Path("/some/dir"))
        cmd = mock_run.call_args.args[0]
        assert cmd == ["rm", "-rf", "/some/dir"]
