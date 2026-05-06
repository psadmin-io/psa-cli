"""Tests for psa dpk facts init / set / list."""

import json
from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.commands.dpk.facts import (
    FACTS_D_HEADER,
    KNOWN_FACTS,
    KNOWN_ROLES,
    _format_server_yaml,
    _resolve_facts_d,
)
from psa.core.config import PsaConfig

runner = CliRunner()


# --- helpers ---


def test_known_roles_match_spec():
    assert KNOWN_ROLES == ["app", "appbat", "web", "prcs", "mid", "webapp"]


def test_known_facts_match_spec():
    assert KNOWN_FACTS == ["ps_role", "env", "ps_tier", "ps_zone", "ps_pillar"]


def test_format_server_yaml_includes_header_and_body():
    out = _format_server_yaml({"ps_role": "mid", "env": "FSCMDEV"})
    assert out.startswith(FACTS_D_HEADER)
    assert "ps_role: mid" in out
    assert "env: FSCMDEV" in out


def test_format_server_yaml_empty_dict_is_header_only():
    out = _format_server_yaml({})
    assert out == FACTS_D_HEADER


def test_format_server_yaml_preserves_insertion_order():
    out = _format_server_yaml({"ps_role": "mid", "env": "X", "ps_tier": "DEV"})
    body = out[len(FACTS_D_HEADER):]
    # yaml.safe_dump with sort_keys=False preserves dict insertion order
    assert body.index("ps_role") < body.index("env") < body.index("ps_tier")


# --- _resolve_facts_d ---


def test_resolve_facts_d_uses_dpk_base_first(tmp_path, monkeypatch):
    monkeypatch.delenv("DPK_BASE", raising=False)
    primary = tmp_path / "psft_puppet_agent" / "facter" / "facts.d"
    primary.mkdir(parents=True)
    result = _resolve_facts_d(tmp_path)
    assert result == primary


def test_resolve_facts_d_falls_back_to_puppetlabs(tmp_path, monkeypatch):
    """When primary doesn't exist, prefer /opt/puppetlabs if it does."""
    monkeypatch.delenv("DPK_BASE", raising=False)
    fake_puppetlabs = tmp_path / "puppetlabs"
    fake_puppetlabs.mkdir()
    with patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(fake_puppetlabs), "/etc/facter/facts.d"]):
        result = _resolve_facts_d(tmp_path)
    assert result == fake_puppetlabs


def test_resolve_facts_d_returns_primary_when_none_exist(tmp_path, monkeypatch):
    """If nothing exists, return the primary path so caller can create it."""
    monkeypatch.delenv("DPK_BASE", raising=False)
    with patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", ["/nonexistent/a", "/nonexistent/b"]):
        result = _resolve_facts_d(tmp_path)
    assert result == tmp_path / "psft_puppet_agent" / "facter" / "facts.d"


def test_resolve_facts_d_uses_dpk_base_env(tmp_path, monkeypatch):
    base = tmp_path / "psft"
    base.mkdir()
    monkeypatch.setenv("DPK_BASE", str(base))
    with patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", []):
        result = _resolve_facts_d(None)
    assert result == base / "psft_puppet_agent" / "facter" / "facts.d"


# --- facts init ---


def _set_facts_d(monkeypatch, tmp_path):
    """Make _resolve_facts_d resolve to <tmp_path>/facts.d/."""
    facts_d = tmp_path / "facts.d"
    facts_d.mkdir()
    monkeypatch.setattr("psa.commands.dpk.facts._resolve_facts_d", lambda dpk_path: facts_d)
    return facts_d


def test_init_writes_yaml(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(
            dpk_app,
            ["facts", "init", "--role", "mid", "--env", "FSCMDEV", "--tier", "DEV", "--zone", "nonprod"],
        )

    assert result.exit_code == 0, result.output
    server = facts_d / "server.yaml"
    assert server.exists()
    content = server.read_text()
    assert content.startswith(FACTS_D_HEADER)
    data = yaml.safe_load(content)
    assert data == {"ps_role": "mid", "env": "FSCMDEV", "ps_tier": "DEV", "ps_zone": "nonprod"}
    assert "Server identity configured" in result.output


def test_init_dry_run_writes_nothing(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(
            dpk_app,
            ["facts", "init", "--role", "app", "--dry-run"],
        )

    assert result.exit_code == 0
    assert not (facts_d / "server.yaml").exists()
    assert "Dry run" in result.output


def test_init_rejects_unknown_role(tmp_path, monkeypatch):
    _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "init", "--role", "bogus"])

    assert result.exit_code != 0
    assert "Unknown role" in result.output


def test_init_requires_at_least_one_fact(tmp_path, monkeypatch):
    _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "init"])

    assert result.exit_code != 0
    assert "No facts specified" in result.output


def test_init_only_includes_passed_flags(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "init", "--role", "app", "--tier", "DEV"])

    assert result.exit_code == 0
    data = yaml.safe_load((facts_d / "server.yaml").read_text())
    assert data == {"ps_role": "app", "ps_tier": "DEV"}
    assert "env" not in data
    assert "ps_zone" not in data


def test_init_backs_up_existing(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    server = facts_d / "server.yaml"
    server.write_text("ps_role: old\n")

    config = PsaConfig(sudo_enabled=False)
    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "init", "--role", "mid"])

    assert result.exit_code == 0
    assert server.read_text().endswith("ps_role: mid\n")
    backup = facts_d / "server.yaml.bak"
    assert backup.exists()
    assert backup.read_text() == "ps_role: old\n"


# --- facts set ---


def test_set_creates_new_file(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "set", "ps_role", "mid"])

    assert result.exit_code == 0
    server = facts_d / "server.yaml"
    assert server.exists()
    assert yaml.safe_load(server.read_text()) == {"ps_role": "mid"}


def test_set_updates_existing_key(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    server = facts_d / "server.yaml"
    server.write_text("ps_role: app\nenv: FSCMDEV\n")

    config = PsaConfig(sudo_enabled=False)
    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "set", "ps_role", "mid"])

    assert result.exit_code == 0
    data = yaml.safe_load(server.read_text())
    assert data == {"ps_role": "mid", "env": "FSCMDEV"}


def test_set_preserves_other_keys(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    server = facts_d / "server.yaml"
    server.write_text("ps_role: mid\nenv: FSCMDEV\nps_tier: DEV\nextra_key: kept\n")

    config = PsaConfig(sudo_enabled=False)
    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "set", "ps_zone", "nonprod"])

    assert result.exit_code == 0
    data = yaml.safe_load(server.read_text())
    assert data == {
        "ps_role": "mid",
        "env": "FSCMDEV",
        "ps_tier": "DEV",
        "extra_key": "kept",
        "ps_zone": "nonprod",
    }


def test_set_warns_unknown_key_but_allows(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "set", "weird_fact", "yes"])

    assert result.exit_code == 0
    assert "Unknown fact key" in result.output
    data = yaml.safe_load((facts_d / "server.yaml").read_text())
    assert data == {"weird_fact": "yes"}


# --- facts list ---


def test_list_human(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    (facts_d / "server.yaml").write_text("ps_role: mid\nenv: FSCMDEV\n")

    config = PsaConfig(sudo_enabled=False)
    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "list"])

    assert result.exit_code == 0
    assert "ps_role: mid" in result.output
    assert "env: FSCMDEV" in result.output


def test_list_json(tmp_path, monkeypatch):
    facts_d = _set_facts_d(monkeypatch, tmp_path)
    (facts_d / "server.yaml").write_text("ps_role: mid\nenv: FSCMDEV\n")

    config = PsaConfig(sudo_enabled=False)
    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["facts"] == {"ps_role": "mid", "env": "FSCMDEV"}
    assert data["path"].endswith("server.yaml")


def test_list_missing_file_human(tmp_path, monkeypatch):
    _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "list"])

    assert result.exit_code != 0
    assert "psa dpk facts init" in result.output.lower()


def test_list_missing_file_json(tmp_path, monkeypatch):
    _set_facts_d(monkeypatch, tmp_path)
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "list", "--json"])

    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["facts"] is None
