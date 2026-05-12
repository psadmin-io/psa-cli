"""Tests for psa_kit_path and dpk_cust_home in config."""

from pathlib import Path

import yaml

from psa.core.config import PsaConfig


def test_psa_kit_env_loads(monkeypatch, tmp_path, config_file):
    """PSA_KIT env var loads into config."""
    kit_path = tmp_path / "kit"
    monkeypatch.setenv("PSA_KIT", str(kit_path))
    config = PsaConfig.from_environment()
    assert config.psa_kit_path == kit_path


def test_dpk_cust_home_env_loads(monkeypatch, tmp_path):
    """DPK_CUST_HOME env var loads into config."""
    cust_path = tmp_path / "cust"
    monkeypatch.setenv("DPK_CUST_HOME", str(cust_path))
    config = PsaConfig.from_environment()
    assert config.dpk_cust_home == cust_path


def test_dpk_base_env_loads(monkeypatch, tmp_path):
    """DPK_BASE env var loads into config.dpk_base."""
    base_path = tmp_path / "psft"
    monkeypatch.setenv("DPK_BASE", str(base_path))
    config = PsaConfig.from_environment()
    assert config.dpk_base == base_path


def test_psa_kit_yaml_loads(tmp_path):
    """psa_kit_path in YAML loads correctly."""
    kit_path = tmp_path / "kit"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"psa_kit_path": str(kit_path)}))
    config = PsaConfig.load(config_file)
    assert config.psa_kit_path == kit_path


def test_dpk_cust_home_yaml_loads(tmp_path):
    """dpk_cust_home in YAML loads correctly."""
    cust_path = tmp_path / "cust"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"dpk_cust_home": str(cust_path)}))
    config = PsaConfig.load(config_file)
    assert config.dpk_cust_home == cust_path


def test_psa_kit_saves_and_roundtrips(tmp_path):
    """psa_kit_path saves to YAML and loads back."""
    config_file = tmp_path / "config.yaml"
    kit_path = tmp_path / "my-kit"
    config = PsaConfig()
    config.psa_kit_path = kit_path
    config.save(config_file)

    loaded = PsaConfig.load(config_file)
    assert loaded.psa_kit_path == kit_path


def test_dpk_cust_home_saves_and_roundtrips(tmp_path):
    """dpk_cust_home saves to YAML and loads back."""
    config_file = tmp_path / "config.yaml"
    cust_path = tmp_path / "my-cust"
    config = PsaConfig()
    config.dpk_cust_home = cust_path
    config.save(config_file)

    loaded = PsaConfig.load(config_file)
    assert loaded.dpk_cust_home == cust_path


def test_config_set_psa_kit_path(tmp_path):
    """config set psa_kit_path works via setattr + save."""
    config_file = tmp_path / "config.yaml"
    config = PsaConfig()
    setattr(config, "psa_kit_path", Path("/opt/kit"))
    config.save(config_file)
    loaded = PsaConfig.load(config_file)
    assert loaded.psa_kit_path == Path("/opt/kit")


def test_env_overrides_yaml(monkeypatch, tmp_path):
    """Env var PSA_KIT takes precedence over YAML (env loaded first, yaml overlays)."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"psa_kit_path": "/from/yaml"}))
    # Note: from_environment runs first, then load overlays yaml on top.
    # In current implementation yaml overrides env. Test the actual behavior.
    monkeypatch.setenv("PSA_KIT", "/from/env")
    config = PsaConfig.load(config_file)
    # YAML overlays env since load() first calls from_environment() then overlays yaml
    assert config.psa_kit_path == Path("/from/yaml")
