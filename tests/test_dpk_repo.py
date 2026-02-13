"""Tests for DPK repository feature."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import PsaConfig
from psa.core.dpk_repo import DpkRepo, DpkVersion

runner = CliRunner()


# --- Fixtures ---


@pytest.fixture
def mock_repo(tmp_path):
    """Create a mock DPK repo with PCM directory structure."""
    repo = tmp_path / "tools"
    # 862.04 - 3 zips
    v862_04 = repo / "862" / "04"
    v862_04.mkdir(parents=True)
    (v862_04 / "PT862_1of5.zip").write_bytes(b"x" * 1000)
    (v862_04 / "PT862_2of5.zip").write_bytes(b"x" * 2000)
    (v862_04 / "PT862_3of5.zip").write_bytes(b"x" * 3000)

    # 862.03 - 2 zips
    v862_03 = repo / "862" / "03"
    v862_03.mkdir(parents=True)
    (v862_03 / "PT862_1of5.zip").write_bytes(b"x" * 500)
    (v862_03 / "PT862_2of5.zip").write_bytes(b"x" * 500)

    # 860.18 - 1 zip
    v860_18 = repo / "860" / "18"
    v860_18.mkdir(parents=True)
    (v860_18 / "PT860_1of3.zip").write_bytes(b"x" * 4000)

    # Empty dir (no zips) should be excluded
    empty = repo / "862" / "99"
    empty.mkdir(parents=True)

    # Non-numeric dir should be ignored
    (repo / "README").mkdir(parents=True)

    return repo


# --- DpkRepo.list_versions ---


class TestDpkRepoListVersions:
    def test_lists_all_versions(self, mock_repo):
        repo = DpkRepo(mock_repo)
        versions = repo.list_versions()
        assert len(versions) == 3
        assert versions[0].label == "862.04"
        assert versions[1].label == "862.03"
        assert versions[2].label == "860.18"

    def test_filter_by_major(self, mock_repo):
        repo = DpkRepo(mock_repo)
        versions = repo.list_versions(filter_major="862")
        assert len(versions) == 2
        assert all(v.major == "862" for v in versions)

    def test_filter_no_match(self, mock_repo):
        repo = DpkRepo(mock_repo)
        versions = repo.list_versions(filter_major="999")
        assert versions == []

    def test_empty_repo(self, tmp_path):
        repo = DpkRepo(tmp_path / "nonexistent")
        versions = repo.list_versions()
        assert versions == []

    def test_skips_empty_version_dirs(self, mock_repo):
        """Version dirs with no zips should not appear."""
        repo = DpkRepo(mock_repo)
        labels = [v.label for v in repo.list_versions()]
        assert "862.99" not in labels

    def test_zip_count_and_size(self, mock_repo):
        repo = DpkRepo(mock_repo)
        versions = repo.list_versions()
        v862_04 = next(v for v in versions if v.label == "862.04")
        assert v862_04.zip_count == 3
        assert v862_04.total_size == 6000


# --- DpkRepo.resolve_version ---


class TestDpkRepoResolveVersion:
    def test_explicit_version(self, mock_repo):
        repo = DpkRepo(mock_repo)
        path = repo.resolve_version("862.04")
        assert path == mock_repo / "862" / "04"

    def test_latest_when_none(self, mock_repo):
        repo = DpkRepo(mock_repo)
        path = repo.resolve_version(None)
        # Should return the latest (862.04)
        assert path == mock_repo / "862" / "04"

    def test_missing_version_raises(self, mock_repo):
        repo = DpkRepo(mock_repo)
        with pytest.raises(FileNotFoundError):
            repo.resolve_version("999.01")

    def test_bad_format_raises(self, mock_repo):
        repo = DpkRepo(mock_repo)
        with pytest.raises(ValueError, match="Invalid version format"):
            repo.resolve_version("862")

    def test_empty_repo_raises(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        repo = DpkRepo(empty)
        with pytest.raises(FileNotFoundError):
            repo.resolve_version(None)


# --- DpkVersion ---


class TestDpkVersion:
    def test_label(self):
        v = DpkVersion(major="862", minor="04", path=Path("/x"), zip_count=3, total_size=0)
        assert v.label == "862.04"

    def test_human_size_gb(self):
        v = DpkVersion(major="862", minor="04", path=Path("/x"), zip_count=3, total_size=2_147_483_648)
        assert "GB" in v.human_size

    def test_human_size_mb(self):
        v = DpkVersion(major="862", minor="04", path=Path("/x"), zip_count=3, total_size=5_242_880)
        assert "MB" in v.human_size

    def test_human_size_kb(self):
        v = DpkVersion(major="862", minor="04", path=Path("/x"), zip_count=3, total_size=1024)
        assert "KB" in v.human_size


# --- repo init command ---


class TestRepoInit:
    @patch("psa.commands.dpk.repo.PsaConfig.save")
    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_init_saves_config(self, mock_load, mock_save, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        cfg = PsaConfig()
        mock_load.return_value = cfg

        result = runner.invoke(psa_app, ["dpk", "repo", "init", "--path", str(repo_dir)])
        assert result.exit_code == 0
        assert cfg.dpk_repo_path == str(repo_dir)
        mock_save.assert_called_once()

    def test_init_missing_dir_fails(self, tmp_path):
        result = runner.invoke(psa_app, ["dpk", "repo", "init", "--path", str(tmp_path / "missing")])
        assert result.exit_code == 1
        assert "not found" in result.output


# --- repo status command ---


class TestRepoStatus:
    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_status_not_configured(self, mock_load):
        mock_load.return_value = PsaConfig()
        result = runner.invoke(psa_app, ["dpk", "repo", "status"])
        assert result.exit_code == 1
        assert "not configured" in result.output

    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_status_shows_info(self, mock_load, mock_repo):
        cfg = PsaConfig(dpk_repo_path=str(mock_repo))
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["dpk", "repo", "status"])
        assert result.exit_code == 0
        assert "accessible" in result.output
        assert "862.04" in result.output

    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_status_missing_path(self, mock_load, tmp_path):
        cfg = PsaConfig(dpk_repo_path=str(tmp_path / "gone"))
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["dpk", "repo", "status"])
        assert result.exit_code == 1
        assert "not found" in result.output


# --- repo list command ---


class TestRepoList:
    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_list_all(self, mock_load, mock_repo):
        cfg = PsaConfig(dpk_repo_path=str(mock_repo))
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["dpk", "repo", "list"])
        assert result.exit_code == 0
        assert "862.04" in result.output
        assert "862.03" in result.output
        assert "860.18" in result.output
        assert "3 version(s)" in result.output

    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_list_filter_major(self, mock_load, mock_repo):
        cfg = PsaConfig(dpk_repo_path=str(mock_repo))
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["dpk", "repo", "list", "--version", "860"])
        assert result.exit_code == 0
        assert "860.18" in result.output
        assert "862" not in result.output
        assert "1 version(s)" in result.output

    @patch("psa.commands.dpk.repo.PsaConfig.load")
    def test_list_not_configured(self, mock_load):
        mock_load.return_value = PsaConfig()
        result = runner.invoke(psa_app, ["dpk", "repo", "list"])
        assert result.exit_code == 1
        assert "not configured" in result.output


# --- stage --version ---


class TestStageVersion:
    @patch("psa.commands.dpk.core.get_config")
    def test_version_no_repo_configured(self, mock_get_config):
        """--version without dpk_repo_path should error."""
        mock_get_config.return_value = PsaConfig()
        result = runner.invoke(psa_app, ["dpk", "stage", "--version", "862.04", "--install-dir", "/tmp/x"])
        assert result.exit_code == 1
        assert "dpk_repo_path" in result.output

    @patch("psa.commands.dpk.core.get_config")
    def test_version_resolves_repo(self, mock_get_config, mock_repo):
        """--version with configured repo should resolve to version dir."""
        cfg = PsaConfig(dpk_repo_path=str(mock_repo))
        mock_get_config.return_value = cfg
        result = runner.invoke(psa_app, [
            "dpk", "stage",
            "--version", "862.04",
            "--install-dir", "/tmp/dpk-test",
            "--dry-run",
        ])
        # Resolution succeeds (rest of dry-run fails because files aren't copied)
        assert "Resolved from DPK repo" in result.output
        assert str(mock_repo / "862" / "04") in result.output

    @patch("psa.commands.dpk.core.get_config")
    def test_version_missing_raises(self, mock_get_config, mock_repo):
        """--version for nonexistent version should error."""
        cfg = PsaConfig(dpk_repo_path=str(mock_repo))
        mock_get_config.return_value = cfg
        result = runner.invoke(psa_app, ["dpk", "stage", "--version", "999.01", "--install-dir", "/tmp/x"])
        assert result.exit_code == 1
        assert "not found" in result.output


# --- config set dpk_repo_path ---


class TestConfigSetDpkRepoPath:
    @patch("psa.commands.config.PsaConfig.save")
    @patch("psa.commands.config.PsaConfig.load")
    def test_set_dpk_repo_path(self, mock_load, mock_save):
        cfg = PsaConfig()
        mock_load.return_value = cfg
        result = runner.invoke(psa_app, ["config", "set", "dpk_repo_path", "/nfs/dpk"])
        assert result.exit_code == 0
        assert cfg.dpk_repo_path == "/nfs/dpk"
        mock_save.assert_called_once()
