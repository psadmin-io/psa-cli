"""Tests for psa domain status --report flag."""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest
from typer.testing import CliRunner

from psa.cli import app as psa_app
from psa.core.config import OpsConfig, PsaConfig
from psa.core.domain import DomainInfo

runner = CliRunner()


def _make_domain(name="APPDOM", domain_type="app"):
    return DomainInfo(
        name=name,
        domain_type=domain_type,
        path=Path(f"/fake/{name}"),
        ps_cfg_home=Path("/fake/cfg"),
    )


def _make_psadmin_result(output="processes running", success=True):
    result = MagicMock()
    result.output = output
    result.success = success
    result.exit_code = 0
    return result


class TestStatusReportFlag:
    """Tests for --report flag on domain status command."""

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_report_calls_update_domain(
        self, mock_cache, mock_api_cls, mock_get_config, mock_executor, mock_find
    ):
        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result()
        mock_get_config.return_value = PsaConfig(ops=OpsConfig(url="http://api:8002"))
        mock_cache.return_value = "d1-uuid"

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client

        result = runner.invoke(psa_app, ["domain", "status", "APPDOM", "--report"])
        assert result.exit_code == 0
        mock_client.update_domain.assert_called_once_with("d1-uuid", status="Running")
        assert "reported" in result.output

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    def test_no_report_skips_api(self, mock_executor, mock_find):
        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result()

        with patch("psa.commands.domain.ApiClient") as mock_api_cls:
            result = runner.invoke(psa_app, ["domain", "status", "APPDOM"])
            assert result.exit_code == 0
            mock_api_cls.assert_not_called()

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain.get_config")
    def test_report_ops_not_configured_warns(
        self, mock_get_config, mock_executor, mock_find
    ):
        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result()
        mock_get_config.return_value = PsaConfig(ops=OpsConfig())

        result = runner.invoke(psa_app, ["domain", "status", "APPDOM", "--report"])
        assert result.exit_code == 0
        assert "OPS not configured" in result.output

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_report_cache_miss_warns(
        self, mock_cache, mock_get_config, mock_executor, mock_find
    ):
        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result()
        mock_get_config.return_value = PsaConfig(ops=OpsConfig(url="http://api:8002"))
        mock_cache.return_value = None

        result = runner.invoke(psa_app, ["domain", "status", "APPDOM", "--report"])
        assert result.exit_code == 0
        assert "No cached domain ID" in result.output
        assert "psa discover --push" in result.output

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_report_stopped_domain(
        self, mock_cache, mock_api_cls, mock_get_config, mock_executor, mock_find
    ):
        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result(
            output="not booted", success=True
        )
        mock_get_config.return_value = PsaConfig(ops=OpsConfig(url="http://api:8002"))
        mock_cache.return_value = "d1-uuid"

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client

        result = runner.invoke(psa_app, ["domain", "status", "APPDOM", "--report"])
        assert result.exit_code == 0
        mock_client.update_domain.assert_called_once_with("d1-uuid", status="Stopped")

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_report_unknown_status(
        self, mock_cache, mock_api_cls, mock_get_config, mock_executor, mock_find
    ):
        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result(
            output="some weird output", success=True
        )
        mock_get_config.return_value = PsaConfig(ops=OpsConfig(url="http://api:8002"))
        mock_cache.return_value = "d1-uuid"

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client

        result = runner.invoke(psa_app, ["domain", "status", "APPDOM", "--report"])
        assert result.exit_code == 0
        mock_client.update_domain.assert_called_once_with("d1-uuid", status="Unknown")

    @patch("psa.commands.domain._find_domain")
    @patch("psa.commands.domain._get_executor")
    @patch("psa.commands.domain.get_config")
    @patch("psa.commands.domain.ApiClient")
    @patch("psa.commands.domain.get_cached_domain_id")
    def test_report_api_failure_warns_but_succeeds(
        self, mock_cache, mock_api_cls, mock_get_config, mock_executor, mock_find
    ):
        from psa.core.api import ApiError

        mock_find.return_value = _make_domain()
        mock_executor.return_value.app_status.return_value = _make_psadmin_result()
        mock_get_config.return_value = PsaConfig(ops=OpsConfig(url="http://api:8002"))
        mock_cache.return_value = "d1-uuid"

        mock_client = MagicMock()
        mock_api_cls.return_value = mock_client
        mock_client.update_domain.side_effect = ApiError("server error", status_code=500)

        result = runner.invoke(psa_app, ["domain", "status", "APPDOM", "--report"])
        assert result.exit_code == 0
        assert "report failed" in result.output


class TestUpdateDomainApiClient:
    """Tests for ApiClient.update_domain()."""

    @patch("urllib.request.urlopen")
    def test_update_domain_sends_patch(self, mock_urlopen):
        import json
        from psa.core.api import ApiClient

        resp = MagicMock()
        resp.read.return_value = json.dumps({"id": "d1", "status": "Running"}).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        client = ApiClient(base_url="http://api:8002")
        result = client.update_domain("d1", status="Running")

        req = mock_urlopen.call_args[0][0]
        assert req.method == "PATCH"
        assert "/api/v1/domains/d1" in req.full_url
        body = json.loads(req.data.decode())
        assert body == {"status": "Running"}
        assert result["status"] == "Running"

    @patch("urllib.request.urlopen")
    def test_update_domain_filters_none(self, mock_urlopen):
        import json
        from psa.core.api import ApiClient

        resp = MagicMock()
        resp.read.return_value = json.dumps({"id": "d1"}).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        client = ApiClient(base_url="http://api:8002")
        client.update_domain("d1", status="Running", environment_id=None)

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode())
        assert body == {"status": "Running"}
        assert "environment_id" not in body
