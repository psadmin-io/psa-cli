"""Configuration management commands."""

from typing import Optional

import typer
from rich.console import Console

from psa.core.config import CONFIG_PATH, PsaConfig
from psa.core.hub import HubClient, HubError

console = Console()

app = typer.Typer(
    name="config",
    help="Manage psa configuration",
    no_args_is_help=True,
)


@app.command(name="init")
def config_init(
    hub_url: str = typer.Option(
        ...,
        "--hub-url",
        "-r",
        help="Hub API URL",
    ),
    node_id: str = typer.Option(
        ...,
        "--node-id",
        "-n",
        help="Node ID from hub",
    ),
    environment_id: Optional[str] = typer.Option(
        None,
        "--environment-id",
        "-e",
        help="Environment ID (required if node has no domains)",
    ),
) -> None:
    """
    Initialize config from hub (non-interactive).

    Fetches configuration for this node from the hub and writes
    it to the local config file. Used for automated setup via Ansible.

    Examples:
        psa config init -r http://hub.psaops.local:8000 -n abc-123-uuid
        psa config init -r http://hub:8000 -n abc-123-uuid -e env-456-uuid
    """
    console.print("Fetching config from hub...")
    console.print(f"  Hub: [cyan]{hub_url}[/cyan]")
    console.print(f"  Node ID: [cyan]{node_id[:8]}...[/cyan]")
    if environment_id:
        console.print(f"  Environment ID: [cyan]{environment_id[:8]}...[/cyan]")

    client = HubClient(hub_url)

    try:
        config_yaml = client.get_node_config(node_id, environment_id)
    except HubError as e:
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
    if config.hub.environment_name:
        console.print(f"[green]✓[/green] Environment: [cyan]{config.hub.environment_name}[/cyan]")
    if config.hub.tier:
        console.print(f"[green]✓[/green] Tier: {config.hub.tier}")
    if config.hub.ps_role:
        console.print(f"[green]✓[/green] Role: {config.hub.ps_role}")


@app.command(name="show")
def config_show() -> None:
    """Show current configuration."""
    config = PsaConfig.load()

    console.print("[bold]psa Configuration[/bold]\n")
    console.print(f"Config file: [cyan]{CONFIG_PATH}[/cyan]")

    if not CONFIG_PATH.exists():
        console.print("[yellow]No config file found[/yellow]")
        return

    console.print("\n[bold]Paths:[/bold]")
    console.print(f"  PS Base: {config.ps_base}")
    console.print(f"  IO Base: {config.io_base}")
    if config.ps_cfg_home:
        console.print(f"  PS_CFG_HOME: {config.ps_cfg_home}")
    if config.ps_home:
        console.print(f"  PS_HOME: {config.ps_home}")
    console.print(f"  Domain user: {config.domain_user}")

    if config.hub.is_configured():
        console.print("\n[bold]Hub:[/bold]")
        console.print(f"  URL: {config.hub.url}")
        if config.hub.node_id:
            console.print(f"  Node ID: {config.hub.node_id[:8]}...")
        if config.hub.environment_name:
            console.print(f"  Environment: {config.hub.environment_name}")
        if config.hub.tier:
            console.print(f"  Tier: {config.hub.tier}")
        if config.hub.pillar:
            console.print(f"  Pillar: {config.hub.pillar}")
        if config.hub.ps_role:
            console.print(f"  Role: {config.hub.ps_role}")
    else:
        console.print("\n[yellow]Hub not configured[/yellow]")
