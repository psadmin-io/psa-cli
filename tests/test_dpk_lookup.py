"""Tests for psa dpk lookup."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


@pytest.fixture
def fake_dpk(tmp_path):
    dpk = tmp_path / "psft"
    puppet_dir = dpk / "puppet"
    (puppet_dir / "production" / "manifests").mkdir(parents=True)
    (puppet_dir / "production" / "manifests" / "site.pp").write_text("# site")
    puppet_bin = tmp_path / "psft_puppet_agent" / "bin" / "puppet"
    puppet_bin.parent.mkdir(parents=True)
    puppet_bin.write_text("#!/bin/sh\nexit 0\n")
    puppet_bin.chmod(0o755)
    facts_d = tmp_path / "etc-puppetlabs-facts.d"
    facts_d.mkdir()
    return dpk, facts_d


def _invoke(fake_dpk, extra_args=None, *, rc=0, stdout="", stderr="", config=None):
    dpk, facts_d = fake_dpk
    if config is None:
        config = PsaConfig(ops=OpsConfig(), sudo_enabled=False)

    captured = {}

    def fake_stream(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return rc, stdout, stderr

    args = ["lookup", "oracle_client_version", "--dpk-home", str(dpk)]
    if extra_args:
        args += extra_args

    with patch("psa.commands.dpk.core.get_config", return_value=config), \
         patch("psa.commands.dpk.core.stream_subprocess", side_effect=fake_stream), \
         patch("psa.commands.dpk.facts.FACTS_D_CANDIDATES", [str(facts_d)]):
        result = runner.invoke(dpk_app, args)

    return result, captured


def test_default_renders_as_yaml(fake_dpk):
    result, cap = _invoke(fake_dpk)
    assert result.exit_code == 0
    assert "lookup" in cap["cmd"]
    assert "oracle_client_version" in cap["cmd"]
    # default render
    idx = cap["cmd"].index("--render-as")
    assert cap["cmd"][idx + 1] == "yaml"
    # no --explain by default
    assert "--explain" not in cap["cmd"]


def test_render_as_json_passes_through(fake_dpk):
    result, cap = _invoke(fake_dpk, ["--render-as", "json"])
    assert result.exit_code == 0
    idx = cap["cmd"].index("--render-as")
    assert cap["cmd"][idx + 1] == "json"


def test_explain_flag_added(fake_dpk):
    result, cap = _invoke(fake_dpk, ["--explain"])
    assert result.exit_code == 0
    assert "--explain" in cap["cmd"]


def test_fact_flags_set_facter_env(fake_dpk):
    """sudo_enabled=False -> FACTER_* lives in env, not cmd args."""
    result, cap = _invoke(fake_dpk, ["--env", "FSCMDEV", "--role", "mid"])
    assert result.exit_code == 0
    assert cap["env"].get("FACTER_env") == "FSCMDEV"
    assert cap["env"].get("FACTER_ps_role") == "mid"


def test_server_yaml_facts_skip_facter_env(fake_dpk):
    """When server.yaml supplies a fact and no CLI flag overrides, FACTER_*
    is left unset (Facter reads server.yaml directly)."""
    _, facts_d = fake_dpk
    (facts_d / "server.yaml").write_text("ps_role: mid\nenv: FSCMDEV\n")
    result, cap = _invoke(fake_dpk)
    assert result.exit_code == 0
    assert "FACTER_ps_role" not in cap["env"]
    assert "FACTER_env" not in cap["env"]
    assert "Reading from server.yaml" in result.output


def test_cli_flag_overrides_server_yaml(fake_dpk):
    _, facts_d = fake_dpk
    (facts_d / "server.yaml").write_text("ps_role: mid\n")
    result, cap = _invoke(fake_dpk, ["--role", "app"])
    assert result.exit_code == 0
    assert cap["env"].get("FACTER_ps_role") == "app"


def test_exit_code_passes_through(fake_dpk):
    """puppet lookup exits 1 for undefined key; we should propagate."""
    result, _ = _invoke(fake_dpk, rc=1, stderr="Error: did not find a value\n")
    assert result.exit_code == 1


def test_sudo_path_lifts_facters_into_args(fake_dpk, monkeypatch):
    monkeypatch.setenv("USER", "opc")
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    config = PsaConfig(ops=OpsConfig(), runtime_user="psadm2", sudo_enabled=True)
    result, cap = _invoke(
        fake_dpk, ["--env", "FSCMDEV", "--role", "mid"], config=config,
    )
    assert result.exit_code == 0
    assert cap["cmd"][0] == "sudo"
    assert "FACTER_env=FSCMDEV" in cap["cmd"]
    assert "FACTER_ps_role=mid" in cap["cmd"]
    # env should not carry FACTER_* (they live in cmd args)
    assert not any(k.startswith("FACTER_") for k in cap["env"])


def test_no_sudo_when_runtime_user(fake_dpk, monkeypatch):
    monkeypatch.setenv("USER", "psadm2")
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    config = PsaConfig(ops=OpsConfig(), runtime_user="psadm2", sudo_enabled=True)
    result, cap = _invoke(fake_dpk, ["--env", "FSCMDEV"], config=config)
    assert result.exit_code == 0
    assert cap["cmd"][0] != "sudo"
    assert cap["env"].get("FACTER_env") == "FSCMDEV"
