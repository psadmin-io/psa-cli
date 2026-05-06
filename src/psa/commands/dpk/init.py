"""psa dpk init: scaffold DPK_CUST_HOME directory."""

import os
from pathlib import Path
from typing import Optional

import typer

from psa.commands.dpk.core import (
    DEFAULT_DPK_HOME,
    ENV_DPK_HOME,
    SITE_PP_TEMPLATE,
    _generate_environment_conf,
    _generate_hiera_yaml,
    _resolve_dpk_home,
)
from psa.core.config import (
    CONFIG_PATH,
    DEFAULT_DPK_CUST_HOME,
    PsaConfig,
    get_config,
)
from psa.core.output import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)


def _resolve_dpk_cust_home(path: Optional[Path], config: PsaConfig) -> Path:
    """Resolve DPK_CUST_HOME: --dpk-cust-home -> $DPK_CUST_HOME -> config -> default."""
    if path:
        return path.resolve()
    if env := os.environ.get("DPK_CUST_HOME"):
        return Path(env)
    if config.dpk_cust_home:
        return config.dpk_cust_home
    return Path(DEFAULT_DPK_CUST_HOME)


def scaffold_dpk_cust_home(target: Path, dry_run: bool = False) -> None:
    """Create flat DPK_CUST_HOME directory tree with READMEs and empty stubs.

    Layout (flat — does NOT nest under dpk/puppet/production/):
        <target>/
        ├── README.md
        ├── data/
        │   ├── README.md
        │   ├── common.yaml
        │   └── {domain,server,environment,tier,zone}/README.md
        ├── manifests/
        └── modules/
            └── README.md
    """
    data_dir = target / "data"
    manifests_dir = target / "manifests"
    modules_dir = target / "modules"

    layer_subdirs = ["domain", "server", "environment", "tier", "zone"]

    if dry_run:
        console.print(f"  [dim]Would create: {target}/[/dim]")
        for sub in ["data"] + [f"data/{s}" for s in layer_subdirs] + ["manifests", "modules"]:
            console.print(f"  [dim]Would create: {target / sub}/[/dim]")
        return

    target.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(exist_ok=True)
    manifests_dir.mkdir(exist_ok=True)
    modules_dir.mkdir(exist_ok=True)
    for sub in layer_subdirs:
        (data_dir / sub).mkdir(exist_ok=True)

    # Root README
    root_readme = target / "README.md"
    if not root_readme.exists():
        root_readme.write_text(
            "# DPK_CUST_HOME\n\n"
            "Customer-specific DPK customizations for this environment.\n\n"
            "Layout:\n"
            "- `data/` — Hiera data layers\n"
            "- `manifests/site.pp` — Puppet site manifest\n"
            "- `modules/` — Custom Puppet modules (clone io_role, io_portalwar here)\n"
            "- `hiera.yaml` — Generated Hiera config\n"
            "- `environment.conf` — Generated Puppet environment config\n"
        )

    # Data README
    data_readme = data_dir / "README.md"
    if not data_readme.exists():
        data_readme.write_text(
            "# Hiera Data\n\n"
            "Customer customization layers (highest to lowest priority):\n"
            "- domain/ — Per-domain overrides\n"
            "- server/ — Per-server overrides\n"
            "- environment/ — Environment-level config\n"
            "- tier/ — Tier-level config (DEV, TST, PRD)\n"
            "- zone/ — Zone-role config\n"
            "- common.yaml — Shared customizations\n"
        )

    # Empty common.yaml stub
    common = data_dir / "common.yaml"
    if not common.exists():
        common.write_text(
            "---\n"
            "# Common customizations applied to all nodes.\n"
        )

    # Per-layer READMEs
    layer_descriptions = {
        "domain": "Per-domain overrides. File naming: <domain_name>.yaml",
        "server": "Per-server overrides. File naming: <hostname>.yaml",
        "environment": "Environment-level config. File naming: <env_name>.yaml (e.g., FSCMDEV.yaml)",
        "tier": "Tier-level config. File naming: <tier>.yaml (e.g., DEV.yaml, PRD.yaml)",
        "zone": "Zone-role config. File naming: <zone>-<role>.yaml (e.g., nonprod-app.yaml)",
    }
    for sub, desc in layer_descriptions.items():
        readme = data_dir / sub / "README.md"
        if not readme.exists():
            readme.write_text(f"# {sub.capitalize()} Layer\n\n{desc}\n")

    # Modules README
    modules_readme = modules_dir / "README.md"
    if not modules_readme.exists():
        modules_readme.write_text(
            "# Custom Puppet Modules\n\n"
            "Clone customer-specific Puppet modules here (e.g., io_role, io_portalwar).\n"
            "These take precedence over delivered DPK modules.\n"
        )


def dpk_init(
    dpk_cust_home: Optional[Path] = typer.Option(
        None,
        "--dpk-cust-home",
        "-c",
        help=f"DPK_CUST_HOME path (or $DPK_CUST_HOME, default: {DEFAULT_DPK_CUST_HOME})",
    ),
    dpk_home: Optional[Path] = typer.Option(
        None,
        "--dpk-home",
        "-d",
        help=f"DPK install dir (or ${ENV_DPK_HOME}, default: {DEFAULT_DPK_HOME})",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be created",
    ),
) -> None:
    """
    Scaffold DPK_CUST_HOME with flat layout, hiera.yaml, environment.conf, site.pp.

    Creates a fresh customer customization tree with empty Hiera layers,
    a generated Puppet environment.conf, hiera.yaml, and site.pp manifest.

    Creates ~/.config/psa/config.yaml if it does not already exist.
    For full path auto-detection (PS_CFG_HOME, PS_HOME, etc.), run
    'psa config setup' first or after.

    Examples:
        psa dpk init
        psa dpk init --dpk-cust-home /u01/app/io/dpk-cust --dpk-home /u01/app/psoft/dpk
        psa dpk init --dry-run
    """
    config_was_missing = not CONFIG_PATH.exists()
    config = get_config()
    target = _resolve_dpk_cust_home(dpk_cust_home, config)
    resolved_dpk_home = _resolve_dpk_home(dpk_home)

    print_info(f"DPK_CUST_HOME: {target}")
    print_info(f"DPK_HOME: {resolved_dpk_home}")

    # Refuse to overwrite a non-empty target
    if target.exists() and any(target.iterdir()):
        print_error(f"Destination not empty: {target}")
        print_info("Remove existing files or choose a different --dpk-cust-home")
        raise typer.Exit(1)

    if dry_run:
        console.print("[yellow]Dry run - no changes will be made[/yellow]")

    # Scaffold directories + READMEs
    scaffold_dpk_cust_home(target, dry_run=dry_run)

    # Generate hiera.yaml (kit layer omitted since enable_psa_kit defaults to False)
    hiera_path = target / "hiera.yaml"
    hiera_content = _generate_hiera_yaml(
        target, None, enable_psa_kit=config.enable_psa_kit
    )
    if dry_run:
        console.print(f"  [dim]Would write: {hiera_path}[/dim]")
    else:
        hiera_path.write_text(hiera_content)
        print_success(f"  hiera.yaml -> {hiera_path}")

    # Generate environment.conf
    env_conf_path = target / "environment.conf"
    env_conf_content = _generate_environment_conf(
        target, None, resolved_dpk_home, enable_psa_kit=config.enable_psa_kit
    )
    if dry_run:
        console.print(f"  [dim]Would write: {env_conf_path}[/dim]")
    else:
        env_conf_path.write_text(env_conf_content)
        print_success(f"  environment.conf -> {env_conf_path}")

    # Generate site.pp
    site_pp_path = target / "manifests" / "site.pp"
    if dry_run:
        console.print(f"  [dim]Would write: {site_pp_path}[/dim]")
    else:
        site_pp_path.write_text(SITE_PP_TEMPLATE)
        print_success(f"  site.pp -> {site_pp_path}")

    if dry_run:
        return

    # Save path to config (creates the file on first run)
    config.dpk_cust_home = target
    config.save()
    if config_was_missing:
        print_success(f"Created {CONFIG_PATH}")
        print_info("Run 'psa config setup' to populate PS paths (PS_CFG_HOME, PS_HOME, ...)")
    else:
        print_info(f"Saved dpk_cust_home in {CONFIG_PATH}")

    print_success("DPK_CUST_HOME scaffolded")
    print_info(f"Next: clone modules into {target / 'modules'} then run 'psa dpk sync --dpk-home {resolved_dpk_home}'")
