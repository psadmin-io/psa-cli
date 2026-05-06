"""Tests for psa dpk apply integration with facts.d/server.yaml."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from psa.commands.dpk import app as dpk_app
from psa.commands.dpk.core import _read_server_facts
from psa.core.config import OpsConfig, PsaConfig

runner = CliRunner()


# --- _read_server_facts ---


def test_read_server_facts_prefers_dpk_base(tmp_path):
    facts_d = tmp_path / "psft_puppet_agent" / "facter" / "facts.d"
    facts_d.mkdir(parents=True)
    (facts_d / "server.yaml").write_text("ps_role: mid\nenv: FSCMDEV\n")

    config = PsaConfig(sudo_enabled=False)
    result = _read_server_facts(tmp_path, config)
    assert result == {"ps_role": "mid", "env": "FSCMDEV"}


def test_read_server_facts_returns_empty_when_missing(tmp_path):
    config = PsaConfig(sudo_enabled=False)
    result = _read_server_facts(tmp_path, config)
    assert result == {}


def test_read_server_facts_returns_empty_on_invalid_yaml(tmp_path):
    facts_d = tmp_path / "psft_puppet_agent" / "facter" / "facts.d"
    facts_d.mkdir(parents=True)
    (facts_d / "server.yaml").write_text(": :: bogus :::: yaml")

    config = PsaConfig(sudo_enabled=False)
    result = _read_server_facts(tmp_path, config)
    assert result == {}


def test_read_server_facts_handles_non_dict_yaml(tmp_path):
    """If server.yaml is e.g. a list, return empty dict (don't crash)."""
    facts_d = tmp_path / "psft_puppet_agent" / "facter" / "facts.d"
    facts_d.mkdir(parents=True)
    (facts_d / "server.yaml").write_text("- one\n- two\n")

    config = PsaConfig(sudo_enabled=False)
    result = _read_server_facts(tmp_path, config)
    assert result == {}


# --- apply integration: precedence and FACTER_* env vars ---


@pytest.fixture
def fake_dpk(tmp_path):
    """Build a minimal DPK tree that satisfies apply's path checks.

    apply uses resolved_path.parent to locate psft_puppet_agent, so the
    structure is:
        <tmp_path>/
            psft/                       <- --dpk-path target (resolved_path)
                puppet/production/manifests/site.pp
            psft_puppet_agent/bin/puppet  <- found at resolved_path.parent
    """
    dpk = tmp_path / "psft"
    puppet_dir = dpk / "puppet"
    (puppet_dir / "production" / "manifests").mkdir(parents=True)
    (puppet_dir / "production" / "manifests" / "site.pp").write_text("# site")
    puppet_bin = tmp_path / "psft_puppet_agent" / "bin" / "puppet"
    puppet_bin.parent.mkdir(parents=True)
    puppet_bin.write_text("#!/bin/sh\nexit 0\n")
    puppet_bin.chmod(0o755)
    return dpk


def _write_server_yaml(dpk: Path, content: str) -> None:
    """Write server.yaml under <dpk_base>.parent/psft_puppet_agent (matches apply's layout)."""
    facts_d = dpk.parent / "psft_puppet_agent" / "facter" / "facts.d"
    facts_d.mkdir(parents=True, exist_ok=True)
    (facts_d / "server.yaml").write_text(content)


def _invoke_apply(dpk, extra_args=None, config=None):
    """Run psa dpk apply with subprocess.run mocked so puppet doesn't actually execute."""
    if config is None:
        config = PsaConfig(ops=OpsConfig(), sudo_enabled=False)

    captured = {}

    def fake_run(cmd, **kwargs):
        # Capture the FACTER_* environment vars passed to puppet apply.
        if cmd and "puppet" in str(cmd[0]):
            env = kwargs.get("env", {}) or {}
            captured["facter"] = {k: v for k, v in env.items() if k.startswith("FACTER_")}
        return MagicMock(returncode=0, stdout="", stderr="")

    args = ["apply", "--dpk-path", str(dpk)]
    if extra_args:
        args += extra_args

    with patch("psa.commands.dpk.core.get_config", return_value=config), \
         patch("psa.commands.dpk.core.subprocess.run", side_effect=fake_run):
        result = runner.invoke(dpk_app, args)

    return result, captured.get("facter", {})


def test_apply_no_server_yaml_no_flags_no_facter(fake_dpk):
    """No server.yaml, no flags, no config defaults -> no FACTER_* set."""
    result, facter = _invoke_apply(fake_dpk)
    assert result.exit_code == 0, result.output
    assert facter == {}


def test_apply_cli_flag_sets_facter(fake_dpk):
    """CLI flag always sets FACTER_*."""
    result, facter = _invoke_apply(fake_dpk, ["--role", "app"])
    assert result.exit_code == 0
    assert facter == {"FACTER_ps_role": "app"}


def test_apply_server_yaml_skips_facter(fake_dpk):
    """When server.yaml has the fact and no CLI flag, FACTER_* is NOT set."""
    _write_server_yaml(fake_dpk, "ps_role: mid\nenv: FSCMDEV\nps_tier: DEV\n")
    result, facter = _invoke_apply(fake_dpk)
    assert result.exit_code == 0
    assert facter == {}
    assert "Reading from server.yaml" in result.output
    assert "ps_role" in result.output
    assert "env" in result.output


def test_apply_cli_flag_overrides_server_yaml(fake_dpk):
    """CLI --role overrides ps_role from server.yaml; other facts still left to Facter."""
    _write_server_yaml(fake_dpk, "ps_role: mid\nenv: FSCMDEV\nps_tier: DEV\n")
    result, facter = _invoke_apply(fake_dpk, ["--role", "web"])
    assert result.exit_code == 0
    # Only ps_role should be set as FACTER_ override
    assert facter == {"FACTER_ps_role": "web"}


def test_apply_config_default_used_when_no_server_yaml(fake_dpk):
    """config.ops.tier kicks in when neither CLI flag nor server.yaml provides ps_tier."""
    config = PsaConfig(
        ops=OpsConfig(tier="PRD"),
        sudo_enabled=False,
    )
    result, facter = _invoke_apply(fake_dpk, config=config)
    assert result.exit_code == 0
    assert facter == {"FACTER_ps_tier": "PRD"}
    assert "Using config defaults" in result.output


def test_apply_server_yaml_takes_precedence_over_config_default(fake_dpk):
    """server.yaml wins over config.ops.tier."""
    _write_server_yaml(fake_dpk, "ps_tier: DEV\n")
    config = PsaConfig(
        ops=OpsConfig(tier="PRD"),  # Should be ignored — server.yaml has ps_tier
        sudo_enabled=False,
    )
    result, facter = _invoke_apply(fake_dpk, config=config)
    assert result.exit_code == 0
    assert facter == {}
    # Should NOT show "Using config defaults" for tier since server.yaml supplies it
    assert "Using config defaults" not in result.output


def test_apply_mixed_sources(fake_dpk):
    """CLI overrides one fact, server.yaml supplies another, config default fills a third."""
    _write_server_yaml(fake_dpk, "ps_role: mid\n")
    config = PsaConfig(
        ops=OpsConfig(zone="prod"),
        sudo_enabled=False,
    )
    result, facter = _invoke_apply(fake_dpk, ["--env", "FSCMDEV"], config=config)
    assert result.exit_code == 0
    # CLI: env=FSCMDEV → FACTER_env. config default: zone=prod → FACTER_ps_zone.
    # server.yaml: ps_role=mid → no FACTER_ override.
    assert facter == {"FACTER_env": "FSCMDEV", "FACTER_ps_zone": "prod"}
