"""Configuration management commands."""

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.commands import init
from psa.core.config import CONFIG_PATH, PsaConfig, get_config
from psa.core.domain_cache import get_cached_domain_id
from psa.core.api import ApiClient, ApiError
from psa.core.output import print_error

console = Console()

app = typer.Typer(
    name="config",
    help="Manage PSA-CLI configuration",
    no_args_is_help=True,
)


app.command(name="setup")(init.init)


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
    console.print(f"  PS Base: {config.ps_base}")
    console.print(f"  IO Base: {config.io_base}")
    if config.ps_cfg_home:
        console.print(f"  PS_CFG_HOME: {config.ps_cfg_home}")
    if config.ps_home:
        console.print(f"  PS_HOME: {config.ps_home}")
    if config.ps_app_home:
        console.print(f"  PS_APP_HOME: {config.ps_app_home}")
    if config.ps_cust_home:
        console.print(f"  PS_CUST_HOME: {config.ps_cust_home}")
    if config.multi_homes:
        console.print(f"  Multi-homes: {', '.join(str(p) for p in config.multi_homes)}")
    console.print(f"  Runtime user: {config.runtime_user}")

    console.print("\n[bold]Options:[/bold]")
    console.print(f"  sudo_enabled: {config.sudo_enabled}")
    console.print(f"  parallel_boot: {config.parallel_boot}")
    console.print(f"  skip_domain_confirm: {config.skip_domain_confirm}")

    if config.ops.is_configured():
        console.print("\n[bold]PSA-OPS:[/bold]")
        console.print(f"  URL: {config.ops.url}")
        if config.ops.node_id:
            console.print(f"  Node ID: {config.ops.node_id[:8]}...")
        if config.ops.environment_name:
            console.print(f"  Environment: {config.ops.environment_name}")
        if config.ops.tier:
            console.print(f"  Tier: {config.ops.tier}")
        if config.ops.pillar:
            console.print(f"  Pillar: {config.ops.pillar}")
        if config.ops.zone:
            console.print(f"  Zone: {config.ops.zone}")
        if config.ops.suppress_fact_warnings:
            console.print(f"  Suppress fact warnings: {config.ops.suppress_fact_warnings}")
        if config.ops.ps_role:
            console.print(f"  Role: {config.ops.ps_role}")
    else:
        console.print("\n[yellow]PSA-OPS not configured[/yellow]")


def _resolve_domain_id(client: ApiClient, name: str) -> str:
    """Resolve domain name to UUID. Checks local cache first, then PSA-OPS."""
    cached = get_cached_domain_id(name)
    if cached:
        return cached
    domain = client.resolve_domain(name)
    if not domain:
        print_error(f"Domain '{name}' not found in PSA-OPS")
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
    Compare config across domains

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
        print_error("PSA-OPS not configured. Run 'psa config setup' first")
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
