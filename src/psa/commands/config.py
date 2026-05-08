"""Configuration management commands."""

from typing import Optional

import typer
from rich.console import Console

from psa.commands import init
from pathlib import Path

from psa.core.api import ApiClient, ApiError
from psa.core.config import CONFIG_PATH, PsaConfig, get_config
from psa.core.output import print_error

console = Console()

app = typer.Typer(
    name="config",
    help="Manage PSA-CLI configuration",
    no_args_is_help=True,
)


app.command(name="setup")(init.standalone_setup)


@app.command(name="init", hidden=True)
def config_init(
    ops_url: str = typer.Option(
        ...,
        "--ops-url",
        "-r",
        help="PSA-OPS URL",
    ),
    node_id: str = typer.Option(
        ...,
        "--node-id",
        "-n",
        help="Node ID from PSA-OPS",
    ),
    environment_id: Optional[str] = typer.Option(
        None,
        "--environment-id",
        "-e",
        help="Environment ID (required if node has no domains)",
    ),
) -> None:
    """
    Initialize config from PSA-OPS (non-interactive).

    Fetches configuration for this node from PSA-OPS and writes
    it to the local config file. Used for automated setup via Ansible.

    Examples:
        psa config init -r http://ops.psaops.local:8000 -n abc-123-uuid
        psa config init -r http://ops:8000 -n abc-123-uuid -e env-456-uuid
    """
    console.print("Fetching config from PSA-OPS...")
    console.print(f"  PSA-OPS: [cyan]{ops_url}[/cyan]")
    console.print(f"  Node ID: [cyan]{node_id[:8]}...[/cyan]")
    if environment_id:
        console.print(f"  Environment ID: [cyan]{environment_id[:8]}...[/cyan]")

    client = ApiClient(ops_url)

    try:
        config_yaml = client.get_node_config(node_id, environment_id)
    except ApiError as e:
        console.print(f"[red]✗[/red] Failed to fetch config: {e}")
        raise typer.Exit(1)

    # Ensure config directory exists
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Write config file
    with open(CONFIG_PATH, "w") as f:
        f.write(config_yaml)

    console.print(f"[green]✓[/green] Config written to [cyan]{CONFIG_PATH}[/cyan]")

    # Load and display what was written
    config = PsaConfig.load()
    if config.ops.environment_name:
        console.print(f"[green]✓[/green] Environment: [cyan]{config.ops.environment_name}[/cyan]")
    if config.ops.tier:
        console.print(f"[green]✓[/green] Tier: {config.ops.tier}")
    if config.ops.ps_role:
        console.print(f"[green]✓[/green] Role: {config.ops.ps_role}")


SETTABLE_KEYS = {
    "skip_domain_confirm": ("bool", "Skip confirmation prompt for all-domain commands"),
    "parallel_boot": ("bool", "Use parallelboot instead of boot"),
    "sudo_enabled": ("bool", "Use sudo to run commands as runtime_user"),
    "runtime_user": ("str", "OS user for domain commands"),
    "ps_cfg_home": ("path", "Path to PS_CFG_HOME (PeopleSoft domains root)"),
    "dpk_repo_path": ("path", "Path to DPK file repository (PCM mount or local dir)"),
    "psa_kit_path": ("path", "Path to PSA Kit installation"),
    "dpk_base": ("path", "DPK install parent dir, e.g. /u01/app/psoft (DPK_HOME = dpk_base/dpk)"),
    "dpk_home": ("path", "DPK install dir (overrides dpk_base/dpk)"),
    "dpk_cust_home": ("path", "Path to DPK customer customizations (DPK_CUST_HOME)"),
}


def _parse_bool(value: str) -> bool:
    if value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    raise ValueError(f"Invalid boolean: {value}")


@app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Config key to set"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """
    Set a config value.

    Examples:
        psa config set skip_domain_confirm true
        psa config set parallel_boot true
        psa config set runtime_user psadm3
    """
    if key not in SETTABLE_KEYS:
        print_error(f"Unknown key: {key}")
        console.print(f"[dim]Settable keys: {', '.join(sorted(SETTABLE_KEYS))}[/dim]")
        raise typer.Exit(1)

    val_type, _ = SETTABLE_KEYS[key]
    config = PsaConfig.load()

    try:
        if val_type == "bool":
            setattr(config, key, _parse_bool(value))
        elif val_type == "path":
            setattr(config, key, Path(value))
        else:
            setattr(config, key, value)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    config.save()
    console.print(f"[green]✓[/green] {key} = {getattr(config, key)}")


@app.command(name="show")
def config_show() -> None:
    """Show current configuration"""
    config = PsaConfig.load()

    console.print("[bold]psa Configuration[/bold]\n")
    console.print(f"Config file: [cyan]{CONFIG_PATH}[/cyan]")

    if not CONFIG_PATH.exists():
        console.print("[yellow]No config file found[/yellow]")
        return

    console.print("\n[bold]Paths:[/bold]")
    console.print(f"  DPK_BASE: {config.ps_base}")
    console.print(f"  DPK_HOME: {config.get_dpk_home()}")
    if config.dpk_cust_home:
        console.print(f"  DPK_CUST_HOME: {config.dpk_cust_home}")
    if config.ps_cfg_home:
        console.print(f"  PS_CFG_HOME: {config.ps_cfg_home}")
    if config.ps_home:
        console.print(f"  PS_HOME: {config.ps_home}")
    if config.ps_app_home:
        console.print(f"  PS_APP_HOME: {config.ps_app_home}")
    if config.ps_cust_home:
        console.print(f"  PS_CUST_HOME: {config.ps_cust_home}")
    if config.psa_kit_path:
        console.print(f"  PSA Kit: {config.psa_kit_path}")
    if config.multi_homes:
        console.print(f"  Multi-homes: {', '.join(str(p) for p in config.multi_homes)}")
    console.print(f"  Runtime user: {config.runtime_user}")

    console.print("\n[bold]Options:[/bold]")
    console.print(f"  sudo_enabled: {config.sudo_enabled}")
    console.print(f"  parallel_boot: {config.parallel_boot}")
    console.print(f"  skip_domain_confirm: {config.skip_domain_confirm}")
