"""Tests for HubClient compare, drift, and domain methods."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from psa.core.hub import HubClient, HubError


@pytest.fixture
def client():
    return HubClient(base_url="http://hub:8002")


def _mock_response(data, status=200):
    """Create a mock urllib response."""
    body = json.dumps(data).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestListDomains:
    @patch("urllib.request.urlopen")
    def test_list_all(self, mock_urlopen, client):
        domains = [{"id": "d1", "name": "APPDOM1"}, {"id": "d2", "name": "APPDOM2"}]
        mock_urlopen.return_value = _mock_response(domains)

        result = client.list_domains()
        assert result == domains

        req = mock_urlopen.call_args[0][0]
        assert "/api/v1/domains" in req.full_url
        assert "?" not in req.full_url

    @patch("urllib.request.urlopen")
    def test_list_with_name_filter(self, mock_urlopen, client):
        domains = [{"id": "d1", "name": "APPDOM1"}]
        mock_urlopen.return_value = _mock_response(domains)

        result = client.list_domains(name="APPDOM1")
        assert result == domains

        req = mock_urlopen.call_args[0][0]
        assert "name=APPDOM1" in req.full_url

    @patch("urllib.request.urlopen")
    def test_list_with_node_filter(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response([])

        client.list_domains(node_id="n1")
        req = mock_urlopen.call_args[0][0]
        assert "node_id=n1" in req.full_url


class TestResolveDomain:
    @patch("urllib.request.urlopen")
    def test_resolve_found(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(
            [{"id": "d1", "name": "APPDOM1", "domain_type": "app"}]
        )

        result = client.resolve_domain("APPDOM1")
        assert result["id"] == "d1"

    @patch("urllib.request.urlopen")
    def test_resolve_not_found(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response([])

        result = client.resolve_domain("NONEXIST")
        assert result is None


class TestCompareConfigs:
    @patch("urllib.request.urlopen")
    def test_compare_two_domains(self, mock_urlopen, client):
        compare_result = {
            "rows": [
                {"key": "DBName", "values": {"d1": "HCMPRD", "d2": "HCMPRD"}, "status": "same"},
                {"key": "Port", "values": {"d1": "9100", "d2": "9200"}, "status": "different"},
            ]
        }
        mock_urlopen.return_value = _mock_response(compare_result)

        result = client.compare_configs(["d1", "d2"], config_type="psappsrv.cfg")

        req = mock_urlopen.call_args[0][0]
        assert "domain_ids=d1" in req.full_url
        assert "domain_ids=d2" in req.full_url
        assert "config_type=psappsrv.cfg" in req.full_url
        assert len(result["rows"]) == 2

    @patch("urllib.request.urlopen")
    def test_compare_no_config_type(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response({"rows": []})

        client.compare_configs(["d1", "d2"])
        req = mock_urlopen.call_args[0][0]
        assert "domain_ids=d1" in req.full_url
        assert "config_type" not in req.full_url

    @patch("urllib.request.urlopen")
    def test_compare_hub_error(self, mock_urlopen, client):
        import urllib.error

        error_resp = MagicMock()
        error_resp.read.return_value = b'{"detail":"bad request"}'
        error_resp.fp = True
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=400, msg="", hdrs=None, fp=error_resp
        )

        with pytest.raises(HubError) as exc:
            client.compare_configs(["d1", "d2"])
        assert exc.value.status_code == 400


class TestGetDomainDrift:
    @patch("urllib.request.urlopen")
    def test_drift_with_type(self, mock_urlopen, client):
        drift_data = {
            "changes": [
                {"key": "Port", "old_value": "9100", "new_value": "9200", "change_type": "modified"}
            ]
        }
        mock_urlopen.return_value = _mock_response(drift_data)

        result = client.get_domain_drift("d1", config_type="psappsrv.cfg")
        assert len(result["changes"]) == 1

        req = mock_urlopen.call_args[0][0]
        assert "/api/v1/domains/d1/drift" in req.full_url
        assert "config_type=psappsrv.cfg" in req.full_url

    @patch("urllib.request.urlopen")
    def test_drift_no_type(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response({"changes": []})

        client.get_domain_drift("d1")
        req = mock_urlopen.call_args[0][0]
        assert "/api/v1/domains/d1/drift" in req.full_url
        assert "config_type" not in req.full_url


class TestGetDriftSummary:
    @patch("urllib.request.urlopen")
    def test_summary(self, mock_urlopen, client):
        summary = {
            "config_types": [
                {"config_type": "psappsrv.cfg", "has_drift": True, "change_count": 2, "last_capture": "2026-02-09T12:00:00"},
                {"config_type": "psprcs.cfg", "has_drift": False, "change_count": 0, "last_capture": "2026-02-09T12:00:00"},
            ]
        }
        mock_urlopen.return_value = _mock_response(summary)

        result = client.get_drift_summary("d1")
        assert len(result["config_types"]) == 2

        req = mock_urlopen.call_args[0][0]
        assert "/api/v1/domains/d1/drift/summary" in req.full_url
