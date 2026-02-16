"""Tests for dpk status command (human + JSON output, manifest parsing)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.commands.dpk.core import _parse_manifest, app

runner = CliRunner()

SAMPLE_MANIFEST = """\
type=tools
platform=Linux
version=8.62.07
oracleclient_version=19.3.0.0 Oct2025 CPU
jdk_version=21.0.9 Oct2025 CPU
weblogic_version=14.1.2.0 Oct2025 CPU
tuxedo_version=22.1.0.0.0 RP043
"""


# --- _parse_manifest tests ---


def test_parse_manifest(tmp_path):
    """Parses key=value lines into dict."""
    manifest = tmp_path / "pt-manifest"
    manifest.write_text(SAMPLE_MANIFEST)
    data = _parse_manifest(manifest)
    assert data["version"] == "8.62.07"
    assert data["type"] == "tools"
    assert data["platform"] == "Linux"
    assert data["tuxedo_version"] == "22.1.0.0.0 RP043"
    assert data["jdk_version"] == "21.0.9 Oct2025 CPU"


def test_parse_manifest_empty(tmp_path):
    """Empty file returns empty dict."""
    manifest = tmp_path / "pt-manifest"
    manifest.write_text("")
    data = _parse_manifest(manifest)
    assert data == {}


def test_parse_manifest_whitespace(tmp_path):
    """Strips whitespace around keys and values."""
    manifest = tmp_path / "pt-manifest"
    manifest.write_text("  key  =  value  \n")
    data = _parse_manifest(manifest)
    assert data["key"] == "value"


def test_parse_manifest_no_equals(tmp_path):
    """Lines without = are skipped."""
    manifest = tmp_path / "pt-manifest"
    manifest.write_text("no-equals-here\nkey=val\n")
    data = _parse_manifest(manifest)
    assert data == {"key": "val"}


# --- Helper to build a DPK dir for status tests ---


def _build_dpk(tmp_path, puppet=True, hiera=True, site=True, manifest=True):
    """Build a fake DPK directory tree. Returns (dpk_base, puppet_bin).

    dpk_base is the DPK_BASE directory (e.g. /u01/app/psoft).
    Status command checks dpk_base itself for puppet/ subdir.
    """
    dpk_base = tmp_path / "psoft"
    (dpk_base / "puppet" / "production" / "manifests").mkdir(parents=True)

    if hiera:
        (dpk_base / "puppet" / "production" / "hiera.yaml").write_text("---\n")
    if site:
        (dpk_base / "puppet" / "production" / "manifests" / "site.pp").write_text("node default {}\n")
    if manifest:
        (dpk_base / "pt-manifest").write_text(SAMPLE_MANIFEST)

    puppet_bin = dpk_base / "psft_puppet_agent" / "bin" / "puppet"
    if puppet:
        puppet_bin.parent.mkdir(parents=True)
        puppet_bin.touch(mode=0o755)

    return dpk_base, puppet_bin


def _mock_puppet_run(puppet_bin):
    """Return a side_effect that responds to puppet --version."""
    def side_effect(cmd, **kwargs):
        if str(puppet_bin) in str(cmd) and "--version" in cmd:
            return MagicMock(returncode=0, stdout="8.3.1\n")
        return MagicMock(returncode=1, stdout="")
    return side_effect


# --- status command tests (human-readable) ---


def test_status_all_checks_pass(tmp_path, monkeypatch):
    """All checks pass → 'ready for provisioning'."""
    dpk_base, puppet_bin = _build_dpk(tmp_path)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    with patch("psa.commands.dpk.core.subprocess.run", side_effect=_mock_puppet_run(puppet_bin)):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "ready for provisioning" in result.output


def test_status_no_puppet(tmp_path, monkeypatch):
    """Puppet missing → 'setup incomplete'."""
    dpk_base, _ = _build_dpk(tmp_path, puppet=False)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "setup incomplete" in result.output


def test_status_no_dpk_dir(tmp_path, monkeypatch):
    """No DPK dir → warning about not found."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DPK_BASE", str(empty))

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "not found" in result.output


def test_status_with_manifest(tmp_path, monkeypatch):
    """Manifest exists → shows PT version + middleware."""
    dpk_base, puppet_bin = _build_dpk(tmp_path)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    with patch("psa.commands.dpk.core.subprocess.run", side_effect=_mock_puppet_run(puppet_bin)):
        result = runner.invoke(app, ["status"])

    assert "8.62.07" in result.output
    assert "19.3.0.0" in result.output
    assert "21.0.9" in result.output


def test_status_no_manifest(tmp_path, monkeypatch):
    """DPK dir exists but no pt-manifest → no crash, no version output."""
    dpk_base, puppet_bin = _build_dpk(tmp_path, manifest=False)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    with patch("psa.commands.dpk.core.subprocess.run", side_effect=_mock_puppet_run(puppet_bin)):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "8.62.07" not in result.output
    assert "ready for provisioning" in result.output


# --- status command tests (JSON) ---


def test_status_json_output(tmp_path, monkeypatch):
    """JSON output has expected structure."""
    dpk_base, puppet_bin = _build_dpk(tmp_path)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    with patch("psa.commands.dpk.core.subprocess.run", side_effect=_mock_puppet_run(puppet_bin)):
        result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["puppet"]["installed"] is True
    assert data["puppet"]["version"] == "8.3.1"
    assert data["dpk"]["found"] is True
    assert data["manifest"]["version"] == "8.62.07"
    assert data["hiera"] is True
    assert data["site_manifest"] is True
    assert data["ready"] is True


def test_status_json_no_manifest(tmp_path, monkeypatch):
    """JSON output when manifest missing → manifest is null."""
    dpk_base, puppet_bin = _build_dpk(tmp_path, manifest=False)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    with patch("psa.commands.dpk.core.subprocess.run", side_effect=_mock_puppet_run(puppet_bin)):
        result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["manifest"] is None
    assert data["ready"] is True


def test_status_json_no_puppet(tmp_path, monkeypatch):
    """JSON output when puppet missing."""
    dpk_base, _ = _build_dpk(tmp_path, puppet=False)
    monkeypatch.setenv("DPK_BASE", str(dpk_base))

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["puppet"]["installed"] is False
    assert data["ready"] is False
