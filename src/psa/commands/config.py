"""Configuration management commands."""

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.core.config import CONFIG_PATH, PsaConfig, get_config
from psa.core.domain_cache import get_cached_domain_id
from psa.core.api import ApiClient, ApiError
from psa.core.output import print_error

console = Console()

app = typer.Typer(
    name="config",
    help="Manage psa configuration",
    no_args_is_help=True,
)


@app.command(name="init")
def config_init(
    ops_url: str = typer.Option(
        ...,
        "--ops-url",
        "-r",
        help="OPS API URL",
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
    Initialize config from OPS API (non-interactive).

    Fetches configuration for this node from OPS and writes
    it to the local config file. Used for automated setup via Ansible.

    Examples:
        psa config init -r http://ops.psaops.local:8000 -n abc-123-uuid
        psa config init -r http://ops:8000 -n abc-123-uuid -e env-456-uuid
    """
    console.print("Fetching config from OPS...")
    console.print(f"  OPS: [cyan]{ops_url}[/cyan]")
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

    if config.ops.is_configured():
        console.print("\n[bold]OPS:[/bold]")
        console.print(f"  URL: {config.ops.url}")
        if config.ops.node_id:
            console.print(f"  Node ID: {config.ops.node_id[:8]}...")
        if config.ops.environment_name:
            console.print(f"  Environment: {config.ops.environment_name}")
        if config.ops.tier:
            console.print(f"  Tier: {config.ops.tier}")
        if config.ops.pillar:
            console.print(f"  Pillar: {config.ops.pillar}")
        if config.ops.ps_role:
            console.print(f"  Role: {config.ops.ps_role}")
    else:
        console.print("\n[yellow]OPS not configured[/yellow]")


def _resolve_domain_id(client: ApiClient, name: str) -> str:
    """Resolve domain name to UUID. Checks local cache first, then OPS API."""
    cached = get_cached_domain_id(name)
    if cached:
        return cached
    domain = client.resolve_domain(name)
    if not domain:
        print_error(f"Domain '{name}' not found in OPS")
        raise typer.Exit(1)
    return domain["id"]


@app.command(name="compare")
def config_compare(
    domains: List[str] = typer.Argument(
        ...,
        help="Domain names to compare (at least 2)",
    ),
    config_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Config file type (e.g. psappsrv.cfg, psprcs.cfg)",
    ),
    show_all: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Show all rows including identical values",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
) -> None:
    """
    Compare config across domains.

    Fetches config comparison from PSA-OPS for 2+ domains and displays
    differences. By default only shows 'different' and 'missing' rows.

    Examples:
        psa config compare APPDOM1 APPDOM2
        psa config compare APPDOM1 APPDOM2 --type psappsrv.cfg
        psa config compare APPDOM1 APPDOM2 APPDOM3 --all
    """
    if len(domains) < 2:
        print_error("At least 2 domain names required for comparison")
        raise typer.Exit(1)

    config = get_config()
    if not config.ops.is_configured():
        print_error("OPS not configured. Run 'psa init' first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

    # Resolve names to UUIDs
    domain_ids = []
    for name in domains:
        domain_id = _resolve_domain_id(client, name)
        domain_ids.append(domain_id)

    try:
        result = client.compare_configs(domain_ids, config_type)
    except ApiError as e:
        print_error(f"Compare failed: {e}")
        raise typer.Exit(1)

    if json_output:
        import json
        console.print_json(json.dumps(result, default=str, indent=2))
        return

    rows = result.get("rows", [])
    if not rows:
        console.print("[dim]No config data to compare[/dim]")
        return

    # Filter rows unless --all
    if not show_all:
        rows = [r for r in rows if r.get("status") != "same"]

    # Count summary
    all_rows = result.get("rows", [])
    same_count = sum(1 for r in all_rows if r.get("status") == "same")
    diff_count = sum(1 for r in all_rows if r.get("status") == "different")
    missing_count = sum(1 for r in all_rows if r.get("status") == "missing")

    # Build table
    table = Table(title="Config Comparison")
    table.add_column("Key", style="cyan")
    for name in domains:
        table.add_column(name, style="white")
    table.add_column("Status", style="dim")

    for row in rows:
        status = row.get("status", "")
        values = row.get("values", {})
        style = ""
        if status == "different":
            style = "yellow"
        elif status == "missing":
            style = "red"

        cells = [row.get("key", "")]
        for name in domains:
            val = values.get(name, "")
            cells.append(str(val) if val is not None else "[dim]-[/dim]")
        cells.append(f"[{style}]{status}[/{style}]" if style else status)
        table.add_row(*cells)

    console.print(table)
    console.print(f"\n{same_count} same, {diff_count} different, {missing_count} missing")
