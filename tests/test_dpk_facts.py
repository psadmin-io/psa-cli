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


def test_resolve_facts_d_explicit_override(tmp_path):
    custom = tmp_path / "custom-facts.d"
    custom.mkdir()
    result = _resolve_facts_d(custom)
    assert result == custom.resolve()


def test_resolve_facts_d_prefers_first_existing(tmp_path):
    first = tmp_path / "etc-puppetlabs"
    second = tmp_path / "etc-facter"
    first.mkdir()
    second.mkdir()
    with patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(first), str(second)]):
        result = _resolve_facts_d(None)
    assert result == first


def test_resolve_facts_d_skips_missing_to_existing(tmp_path):
    """If first candidate is missing but second exists, use the second."""
    second = tmp_path / "etc-facter"
    second.mkdir()
    with patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", ["/nonexistent/a", str(second)]):
        result = _resolve_facts_d(None)
    assert result == second


def test_resolve_facts_d_returns_first_when_none_exist():
    """If no candidate exists, return the first (preferred) path so caller can mkdir."""
    with patch(
        "psa.commands.dpk.facts.FACTS_D_CANDIDATES",
        ["/nonexistent/etc-puppetlabs", "/nonexistent/etc-facter"],
    ):
        result = _resolve_facts_d(None)
    assert str(result) == "/nonexistent/etc-puppetlabs"


# --- facts init ---


def _set_facts_d(monkeypatch, tmp_path):
    """Make _resolve_facts_d resolve to <tmp_path>/facts.d/."""
    facts_d = tmp_path / "facts.d"
    facts_d.mkdir()
    monkeypatch.setattr("psa.commands.dpk.facts._resolve_facts_d", lambda facts_dir: facts_d)
    monkeypatch.setattr(
        "psa.commands.dpk.facts._find_existing_server_yaml",
        lambda facts_dir, fileops: facts_d / "server.yaml" if (facts_d / "server.yaml").exists() else None,
    )
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

    with patch("psa.commands.dpk.facts.get_config", return_value=config), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", ["/nonexistent/a", "/nonexistent/b"]):
        # Override the helper to actually search candidates so we exercise the not-found path
        monkeypatch.undo()
        result = runner.invoke(dpk_app, ["facts", "list"])

    assert result.exit_code != 0
    assert "no server.yaml found" in result.output.lower()
    assert "/nonexistent/a/server.yaml" in result.output
    assert "/nonexistent/b/server.yaml" in result.output
    assert "psa dpk facts init" in result.output.lower()


def test_list_missing_file_json(tmp_path, monkeypatch):
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", ["/nonexistent/a"]):
        result = runner.invoke(dpk_app, ["facts", "list", "--json"])

    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["facts"] is None
    assert data["path"] is None
    assert data["searched"] == ["/nonexistent/a/server.yaml"]


def test_list_facts_dir_override(tmp_path):
    """--facts-dir reads from explicit path."""
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "server.yaml").write_text("ps_role: web\n")

    config = PsaConfig(sudo_enabled=False)
    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(dpk_app, ["facts", "list", "--facts-dir", str(custom)])

    assert result.exit_code == 0
    assert "ps_role: web" in result.output


def test_init_facts_dir_override(tmp_path):
    """--facts-dir writes to explicit path."""
    custom = tmp_path / "custom"
    custom.mkdir()
    config = PsaConfig(sudo_enabled=False)

    with patch("psa.commands.dpk.facts.get_config", return_value=config):
        result = runner.invoke(
            dpk_app,
            ["facts", "init", "--role", "mid", "--facts-dir", str(custom)],
        )

    assert result.exit_code == 0, result.output
    assert (custom / "server.yaml").exists()
    data = yaml.safe_load((custom / "server.yaml").read_text())
    assert data == {"ps_role": "mid"}
