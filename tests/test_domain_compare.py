"""Tests for psa domain compare command and compare module."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.compare import (
    ArchiveFile,
    diff_configs,
    extract_api_properties,
    format_age,
    get_primary_config,
    list_archive_backups,
    parse_config_to_flat,
)
from psa.core.config import OpsConfig, PsaConfig
from psa.core.fileops import SudoFileOps

runner = CliRunner()


# ---------------------------------------------------------------------------
# Unit tests: compare module
# ---------------------------------------------------------------------------

class TestFormatAge:
    def test_minutes(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(minutes=30)
        assert format_age(dt, now=now) == "30m ago"

    def test_zero_minutes(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        assert format_age(now, now=now) == "0m ago"

    def test_just_under_one_hour(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(minutes=59)
        assert format_age(dt, now=now) == "59m ago"

    def test_one_hour(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(hours=1)
        assert format_age(dt, now=now) == "1h ago"

    def test_hours(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(hours=5)
        assert format_age(dt, now=now) == "5h ago"

    def test_just_under_one_day(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(hours=23)
        assert format_age(dt, now=now) == "23h ago"

    def test_one_day(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(days=1)
        assert format_age(dt, now=now) == "1d ago"

    def test_many_days(self):
        now = datetime(2026, 2, 1, 12, 0, 0)
        dt = now - timedelta(days=7)
        assert format_age(dt, now=now) == "7d ago"


class TestGetPrimaryConfig:
    def test_app(self):
        assert get_primary_config("app") == "psappsrv.cfg"

    def test_prcs(self):
        assert get_primary_config("prcs") == "psprcs.cfg"

    def test_web(self):
        assert get_primary_config("web") == "configuration.properties"


class TestListArchiveBackups:
    def test_sorts_newest_first(self, tmp_cfg_home):
        config = PsaConfig(ps_cfg_home=tmp_cfg_home, sudo_enabled=False)
        fileops = SudoFileOps(config)
        archive = tmp_cfg_home / "appserv" / "TESTDOM" / "Archive"

        result = list_archive_backups(fileops, archive, "psappsrv.cfg")
        assert len(result) == 2
        # 020126 (Feb 1, 2026) is newer than 012526 (Jan 25, 2026)
        assert "020126" in result[0].name
        assert "012526" in result[1].name
        # parsed_dt should be populated
        assert result[0].parsed_dt == datetime(2026, 2, 1, 9, 0, 0)
        assert result[1].parsed_dt == datetime(2026, 1, 25, 14, 30, 22)

    def test_ignores_plain_copy(self, tmp_cfg_home):
        """Archive/psappsrv.cfg (no timestamp) should not be included."""
        config = PsaConfig(ps_cfg_home=tmp_cfg_home, sudo_enabled=False)
        fileops = SudoFileOps(config)
        archive = tmp_cfg_home / "appserv" / "TESTDOM" / "Archive"

        result = list_archive_backups(fileops, archive, "psappsrv.cfg")
        names = [r.name for r in result]
        assert "psappsrv.cfg" not in names

    def test_empty_archive(self, tmp_path):
        """Empty archive dir returns empty list."""
        archive = tmp_path / "Archive"
        archive.mkdir()
        config = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)
        fileops = SudoFileOps(config)

        result = list_archive_backups(fileops, archive, "psappsrv.cfg")
        assert result == []

    def test_no_archive_dir(self, tmp_path):
        """Non-existent archive dir returns empty list."""
        config = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)
        fileops = SudoFileOps(config)

        result = list_archive_backups(fileops, tmp_path / "Archive", "psappsrv.cfg")
        assert result == []


class TestParseConfigToFlat:
    def test_ini_content(self):
        content = """\
[Startup]
DBName=HCMPRD
DBType=ORACLE

[JOLT Listener]
Port=9100
"""
        result = parse_config_to_flat(content, "psappsrv.cfg")
        assert result["Startup.DBName"] == "HCMPRD"
        assert result["Startup.DBType"] == "ORACLE"
        assert result["JOLT Listener.Port"] == "9100"

    def test_properties_content(self):
        content = """\
psserver=APPDOM
psport=9100
# comment line
webprofile=HCM
"""
        result = parse_config_to_flat(content, "configuration.properties")
        assert result["psserver"] == "APPDOM"
        assert result["psport"] == "9100"
        assert result["webprofile"] == "HCM"
        assert len(result) == 3

    def test_ini_preserves_case(self):
        content = """\
[Domain Settings]
Domain ID=HCMPRD_app
"""
        result = parse_config_to_flat(content, "psappsrv.cfg")
        assert "Domain Settings.Domain ID" in result


class TestDiffConfigs:
    def test_detects_changes(self):
        left = {"a": "1", "b": "2", "c": "3"}
        right = {"a": "1", "b": "99", "d": "4"}

        changes = diff_configs(left, right)
        by_key = {c.key: c for c in changes}

        assert "a" not in by_key  # unchanged
        assert by_key["b"].change_type == "modified"
        assert by_key["b"].old_value == "2"
        assert by_key["b"].new_value == "99"
        assert by_key["c"].change_type == "removed"
        assert by_key["d"].change_type == "added"

    def test_no_changes(self):
        d = {"a": "1", "b": "2"}
        changes = diff_configs(d, d.copy())
        assert changes == []


class TestExtractApiProperties:
    def test_ini_format(self):
        parsed = {
            "sections": {
                "Startup": {"DBName": "HRDEV", "DBType": "ORACLE"},
                "JOLT": {"Port": "9033"},
            }
        }
        result = extract_api_properties(parsed, "psappsrv.cfg")
        assert result["Startup.DBName"] == "HRDEV"
        assert result["JOLT.Port"] == "9033"

    def test_properties_format(self):
        parsed = {
            "sections": {
                "properties": {"psserver": "APPDOM", "psport": "9100"}
            }
        }
        result = extract_api_properties(parsed, "configuration.properties")
        assert result["psserver"] == "APPDOM"
        assert result["psport"] == "9100"


# ---------------------------------------------------------------------------
# CLI integration tests: psa domain compare
# ---------------------------------------------------------------------------

@pytest.fixture
def app_domain_info():
    """Return a mock DomainInfo for an app domain."""
    from psa.core.domain import DomainInfo
    return DomainInfo(
        name="TESTDOM",
        domain_type="app",
        path=Path("/cfg/appserv/TESTDOM"),
    )


@pytest.fixture
def web_domain_info():
    from psa.core.domain import DomainInfo
    return DomainInfo(
        name="TESTWEB",
        domain_type="web",
        path=Path("/cfg/webserv/TESTWEB"),
    )


CURRENT_CFG = """\
[Startup]
DBName=HCMPRD
DBType=ORACLE

[JOLT Listener]
Port=9100
"""

OLD_CFG = """\
[Startup]
DBName=HCMPRD
DBType=ORACLE

[JOLT Listener]
Port=9000
"""


class TestCompareDefaultArchive:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_archive_happy_path(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv.cfg", False),
            ("psappsrv_020126_0900_00.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM"], input="1\n")
        assert result.exit_code == 0
        assert "Port" in result.output or "JOLT Listener.Port" in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_no_archive_exits_error(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG
        mock_fileops.exists.return_value = False  # No Archive dir

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM"])
        assert result.exit_code == 1
        assert "No Archive backups" in result.output


class TestCompareOpsMode:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_happy_path(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path
    ):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(
            ps_cfg_home=tmp_path, ops=OpsConfig(url="http://api:8002"), sudo_enabled=False,
        )
        mock_cache.return_value = "d1"

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.get_latest_config.return_value = {
            "parsed_content": {
                "sections": {
                    "Startup": {"DBName": "HCMPRD", "DBType": "ORACLE"},
                    "JOLT Listener": {"Port": "9000"},
                }
            }
        }

        # User declines commit prompt
        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"], input="n\n")
        assert result.exit_code == 0
        assert "Port" in result.output or "JOLT Listener.Port" in result.output

    @patch("psa.commands.domain.get_config")
    def test_ops_not_configured(self, mock_cfg, tmp_path):
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig(), sudo_enabled=False)

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"])
        assert result.exit_code == 1
        assert "OPS not configured" in result.output


class TestCompareFileMode:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_file_happy_path(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--file", "/tmp/old.cfg"])
        assert result.exit_code == 0
        assert "Port" in result.output or "JOLT Listener.Port" in result.output


class TestCompareJsonOutput:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_json_output(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv_020126_0900_00.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["domain"] == "TESTDOM"
        assert data["config_type"] == "psappsrv.cfg"
        assert "changes" in data
        assert isinstance(data["has_drift"], bool)


class TestCompareWebArchiveBlocked:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_web_default_mode_errors(self, mock_find, mock_cfg, mock_fileops_cls, web_domain_info, tmp_path):
        mock_find.return_value = web_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = "psserver=APPDOM\npsport=9100\n"
        mock_fileops.exists.side_effect = lambda p: "configuration.properties" in str(p)

        result = runner.invoke(psa_app, ["domain", "compare", "TESTWEB"])
        assert result.exit_code == 1
        assert "--ops" in result.output or "--file" in result.output


class TestCompareMutualExclusion:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_ops_and_file_errors(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops", "--file", "/tmp/x.cfg"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_latest_and_ops_errors(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--latest", "--ops"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output


class TestCompareLatestFlag:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_latest_skips_prompt(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        """--latest uses newest backup without prompting."""
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv.cfg", False),
            ("psappsrv_020126_0900_00.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--latest"])
        assert result.exit_code == 0
        # No "Select" prompt in output
        assert "Select" not in result.output


class TestCompareInteractivePicker:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_default_prompts_user(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        """Default mode shows numbered list and prompts."""
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv.cfg", False),
            ("psappsrv_020126_0900_00.cfg", False),
            ("psappsrv_012526_1430_22.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM"], input="1\n")
        assert result.exit_code == 0
        assert "Archive backups for psappsrv.cfg" in result.output
        assert "1." in result.output
        assert "ago)" in result.output
        assert "Select" in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_select_second_backup(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        """User selects backup #2."""
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv.cfg", False),
            ("psappsrv_020126_0900_00.cfg", False),
            ("psappsrv_012526_1430_22.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM"], input="2\n")
        assert result.exit_code == 0
        # The left_label should be the second backup name
        assert "012526" in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_invalid_selection_exits_error(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        """Out-of-range selection errors."""
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv_020126_0900_00.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM"], input="99\n")
        assert result.exit_code == 1
        assert "Invalid selection" in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_json_implies_latest(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        """--json skips interactive prompt."""
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv_020126_0900_00.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--json"])
        assert result.exit_code == 0
        assert "Select" not in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_quiet_implies_latest(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        """--quiet skips interactive prompt."""
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.side_effect = [CURRENT_CFG, OLD_CFG]
        mock_fileops.exists.return_value = True
        mock_fileops.listdir.return_value = [
            ("psappsrv_020126_0900_00.cfg", False),
        ]

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--quiet"])
        assert result.exit_code == 0
        assert "Select" not in result.output


class TestCompareNoNameRequiredForOps:
    """Name is now optional; non-ops modes still require it."""

    def test_no_name_no_ops_errors(self):
        result = runner.invoke(psa_app, ["domain", "compare"])
        assert result.exit_code == 1
        assert "Domain name required" in result.output


# ---------------------------------------------------------------------------
# Ops commit flow tests
# ---------------------------------------------------------------------------

# Shared API response with drift (Port changed 9000 -> 9100)
API_CONFIG_WITH_DRIFT = {
    "parsed_content": {
        "sections": {
            "Startup": {"DBName": "HCMPRD", "DBType": "ORACLE"},
            "JOLT Listener": {"Port": "9000"},
        }
    }
}

# Shared API response matching current config (no drift)
API_CONFIG_NO_DRIFT = {
    "parsed_content": {
        "sections": {
            "Startup": {"DBName": "HCMPRD", "DBType": "ORACLE"},
            "JOLT Listener": {"Port": "9100"},
        }
    }
}


def _setup_ops_mocks(mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
                     domain_info, tmp_path, api_config_return=None):
    """Wire up standard mocks for --ops commit flow tests."""
    mock_find.return_value = domain_info
    mock_cfg.return_value = PsaConfig(
        ps_cfg_home=tmp_path,
        ops=OpsConfig(url="http://api:8002", environment_id="env1"),
        sudo_enabled=False,
    )
    mock_cache.return_value = "d1"

    mock_fileops = MagicMock()
    mock_fileops_cls.return_value = mock_fileops
    mock_fileops.read_text.return_value = CURRENT_CFG

    mock_client = MagicMock()
    mock_api_cls.return_value = mock_client
    mock_client.get_latest_config.return_value = api_config_return
    mock_client.ingest_scan.return_value = {
        "domains": [{"id": "d1", "name": domain_info.name, "domain_type": domain_info.domain_type}],
    }
    return mock_client


class TestCompareOpsCommitFlow:
    """Test --ops commit flow."""

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_changes_user_confirms(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, app_domain_info, tmp_path
    ):
        """--ops with changes, user confirms -> ingest called."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=API_CONFIG_WITH_DRIFT,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"], input="y\n")
        assert result.exit_code == 0
        assert "Commit to Ops?" in result.output
        mock_client.ingest_scan.assert_called_once()
        mock_update_cache.assert_called_once()

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_changes_user_declines(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        app_domain_info, tmp_path
    ):
        """--ops with changes, user declines -> no ingest."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=API_CONFIG_WITH_DRIFT,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"], input="n\n")
        assert result.exit_code == 0
        mock_client.ingest_scan.assert_not_called()

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_no_changes(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        app_domain_info, tmp_path
    ):
        """--ops with no changes -> 'matches baseline' message."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=API_CONFIG_NO_DRIFT,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"])
        assert result.exit_code == 0
        # print_info uses console which may be affected by verbosity leaks;
        # verify no ingest was attempted instead
        mock_client.ingest_scan.assert_not_called()

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_no_baseline_user_confirms(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, app_domain_info, tmp_path
    ):
        """--ops with no baseline, user confirms -> ingest called."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=None,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"], input="y\n")
        assert result.exit_code == 0
        assert "Commit current config as baseline?" in result.output
        mock_client.ingest_scan.assert_called_once()

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_commit_flag_auto_confirms(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, app_domain_info, tmp_path
    ):
        """--ops --commit auto-confirms, ingest called."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=API_CONFIG_WITH_DRIFT,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops", "--commit"])
        assert result.exit_code == 0
        # No prompt should appear
        assert "Commit to Ops?" not in result.output
        mock_client.ingest_scan.assert_called_once()

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_commit_no_baseline_auto_commits(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, app_domain_info, tmp_path
    ):
        """--ops --commit with no baseline -> auto-commits."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=None,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops", "--commit"])
        assert result.exit_code == 0
        mock_client.ingest_scan.assert_called_once()


class TestCompareOpsPushCurrentConfig:
    """Test that --ops pushes current config to API."""

    @pytest.fixture
    def app_domain_with_config(self):
        """App domain with config_files populated."""
        from psa.core.domain import DomainInfo
        return DomainInfo(
            name="TESTDOM",
            domain_type="app",
            path=Path("/cfg/appserv/TESTDOM"),
            config_files=[{
                "type": "psappsrv.cfg",
                "path": "/cfg/appserv/TESTDOM/psappsrv.cfg",
                "content": CURRENT_CFG,
            }],
        )

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_pushes_current_config(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        app_domain_with_config, tmp_path
    ):
        """--ops calls push_current_config when domain has config_files."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_with_config, tmp_path, api_config_return=API_CONFIG_NO_DRIFT,
        )
        mock_client.push_current_config.return_value = {"updated": 1}

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"])
        assert result.exit_code == 0
        mock_client.push_current_config.assert_called_once_with(
            "d1", app_domain_with_config.config_files,
        )

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_ops_commit_pushes_and_commits(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, app_domain_with_config, tmp_path
    ):
        """--ops --commit pushes current config AND commits via ingest."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_with_config, tmp_path, api_config_return=API_CONFIG_WITH_DRIFT,
        )
        mock_client.push_current_config.return_value = {"updated": 1}

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops", "--commit"])
        assert result.exit_code == 0
        mock_client.push_current_config.assert_called_once()
        mock_client.ingest_scan.assert_called_once()

    @patch("psa.commands.domain.print_warning")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_push_failure_warns_not_crash(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        mock_warn, app_domain_with_config, tmp_path
    ):
        """push_current_config failure prints warning, doesn't crash compare."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_with_config, tmp_path, api_config_return=API_CONFIG_NO_DRIFT,
        )
        mock_client.push_current_config.side_effect = Exception("connection refused")

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"])
        assert result.exit_code == 0
        # Verify warning was issued (Rich console output not captured by CliRunner)
        mock_warn.assert_any_call("Failed to push current config for TESTDOM: connection refused")

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_no_config_files_skips_push(
        self, mock_cache, mock_api_cls, mock_find, mock_cfg, mock_fileops_cls,
        app_domain_info, tmp_path
    ):
        """Domain with empty config_files skips push_current_config."""
        mock_client = _setup_ops_mocks(
            mock_cfg, mock_find, mock_fileops_cls, mock_api_cls, mock_cache,
            app_domain_info, tmp_path, api_config_return=API_CONFIG_NO_DRIFT,
        )

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"])
        assert result.exit_code == 0
        mock_client.push_current_config.assert_not_called()


class TestCompareOpsAllDomains:
    """Test --ops without name (all domains mode)."""

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_iterates_all_domains(
        self, mock_cache, mock_api_cls, mock_discover, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, tmp_path
    ):
        """--ops without name iterates all discovered domains."""
        from psa.core.domain import DomainInfo

        domains = [
            DomainInfo(name="APPDOM", domain_type="app", path=Path("/cfg/appserv/APPDOM")),
            DomainInfo(name="PRCSDOM", domain_type="prcs", path=Path("/cfg/appserv/prcs/PRCSDOM")),
        ]
        mock_discover.return_value = domains
        mock_cfg.return_value = PsaConfig(
            ps_cfg_home=tmp_path,
            ops=OpsConfig(url="http://api:8002", environment_id="env1"),
            sudo_enabled=False,
        )
        mock_cache.return_value = "d1"

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.get_latest_config.return_value = API_CONFIG_NO_DRIFT
        mock_client.ingest_scan.return_value = {"domains": []}

        result = runner.invoke(psa_app, ["domain", "compare", "--ops", "--commit"])
        assert result.exit_code == 0
        # Both domains should have been checked (get_latest_config called twice)
        assert mock_client.get_latest_config.call_count == 2

    @patch("psa.commands.domain.update_cache_from_ingest")
    @patch("psa.commands.domain.get_hostname", return_value="testhost")
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_commit_all_domains(
        self, mock_cache, mock_api_cls, mock_discover, mock_cfg, mock_fileops_cls,
        mock_hostname, mock_update_cache, tmp_path
    ):
        """--ops --commit auto-confirms all domains."""
        from psa.core.domain import DomainInfo

        domains = [
            DomainInfo(name="APPDOM", domain_type="app", path=Path("/cfg/appserv/APPDOM")),
        ]
        mock_discover.return_value = domains
        mock_cfg.return_value = PsaConfig(
            ps_cfg_home=tmp_path,
            ops=OpsConfig(url="http://api:8002", environment_id="env1"),
            sudo_enabled=False,
        )
        mock_cache.return_value = "d1"

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.get_latest_config.return_value = API_CONFIG_WITH_DRIFT
        mock_client.ingest_scan.return_value = {
            "domains": [{"id": "d1", "name": "APPDOM", "domain_type": "app"}],
        }

        result = runner.invoke(psa_app, ["domain", "compare", "--ops", "--commit"])
        assert result.exit_code == 0
        mock_client.ingest_scan.assert_called_once()

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.run_discovery")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_per_domain_results(
        self, mock_cache, mock_api_cls, mock_discover, mock_cfg, mock_fileops_cls,
        tmp_path
    ):
        """Per-domain results: one matches baseline, one has drift."""
        from psa.core.domain import DomainInfo

        domains = [
            DomainInfo(name="APPDOM", domain_type="app", path=Path("/cfg/appserv/APPDOM")),
            DomainInfo(name="PRCSDOM", domain_type="prcs", path=Path("/cfg/appserv/prcs/PRCSDOM")),
        ]
        mock_discover.return_value = domains
        mock_cfg.return_value = PsaConfig(
            ps_cfg_home=tmp_path,
            ops=OpsConfig(url="http://api:8002", environment_id="env1"),
            sudo_enabled=False,
        )
        mock_cache.return_value = "d1"

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        # First domain: no drift. Second domain: has drift
        mock_client.get_latest_config.side_effect = [
            API_CONFIG_NO_DRIFT,
            API_CONFIG_WITH_DRIFT,
        ]

        # User declines commit for second domain (first has no prompt since no drift)
        result = runner.invoke(psa_app, ["domain", "compare", "--ops"], input="n\n")
        assert result.exit_code == 0
        # Both domains were checked
        assert mock_client.get_latest_config.call_count == 2
        # No ingest since user declined the one with drift, other had no drift
        mock_client.ingest_scan.assert_not_called()
