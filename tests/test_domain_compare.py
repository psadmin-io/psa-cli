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

    def test_pia(self):
        assert get_primary_config("pia") == "configuration.properties"


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
def pia_domain_info():
    from psa.core.domain import DomainInfo
    return DomainInfo(
        name="TESTPIA",
        domain_type="pia",
        path=Path("/cfg/webserv/TESTPIA"),
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

        result = runner.invoke(psa_app, ["domain", "compare", "TESTDOM", "--ops"])
        assert result.exit_code == 0
        assert "Port" in result.output or "JOLT Listener.Port" in result.output

    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_ops_not_configured(self, mock_find, mock_cfg, mock_fileops_cls, app_domain_info, tmp_path):
        mock_find.return_value = app_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, ops=OpsConfig(), sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = CURRENT_CFG

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


class TestComparePiaArchiveBlocked:
    @patch("psa.commands.domain.SudoFileOps")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain._find_domain")
    def test_pia_default_mode_errors(self, mock_find, mock_cfg, mock_fileops_cls, pia_domain_info, tmp_path):
        mock_find.return_value = pia_domain_info
        mock_cfg.return_value = PsaConfig(ps_cfg_home=tmp_path, sudo_enabled=False)

        mock_fileops = MagicMock()
        mock_fileops_cls.return_value = mock_fileops
        mock_fileops.read_text.return_value = "psserver=APPDOM\npsport=9100\n"
        mock_fileops.exists.side_effect = lambda p: "configuration.properties" in str(p)

        result = runner.invoke(psa_app, ["domain", "compare", "TESTPIA"])
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
