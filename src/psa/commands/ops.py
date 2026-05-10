"""PSA-OPS management commands."""

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.commands import init
from psa.core.config import CONFIG_PATH, get_config
from psa.core.domain_cache import get_cached_domain_id
from psa.core.output import print_error, print_success
from psa.core.api import ApiClient, ApiError, get_hostname

console = Console()

app = typer.Typer(
    name="ops",
    help="Manage PSA-OPS API connections and data",
    no_args_is_help=True,
)


app.command(name="setup")(init.ops_setup)


@app.command(name="environments")
def list_environments() -> None:
    """List environments from PSA-OPS"""
    config = get_config()

    if not config.ops.is_configured():
        console.print("[red]PSA-OPS not configured[/red]")
        console.print("Run [cyan]psa ops setup --url <url>[/cyan] first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

    try:
        environments = client.list_environments()
    except ApiError as e:
        console.print(f"[red]Failed to fetch environments:[/red] {e}")
        raise typer.Exit(1)

    if not environments:
        console.print("[dim]No environments found[/dim]")
        return

    table = Table(title="Environments")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Pillar")
    table.add_column("Tier")
    table.add_column("Zone")
    table.add_column("DB Name")

    for env in environments:
        # Mark current environment
        name = env["name"]
        if env["id"] == config.ops.environment_id:
            name = f"[green]{name} \u2713[/green]"

        table.add_row(
            env["id"][:8] + "...",
            name,
            env.get("pillar", "-"),
            env.get("tier", "-"),
            env.get("zone", "-"),
            env.get("db_name", "-"),
        )

    console.print(table)


@app.command(name="nodes")
def list_nodes() -> None:
    """List nodes from PSA-OPS"""
    config = get_config()

    if not config.ops.is_configured():
        console.print("[red]PSA-OPS not configured[/red]")
        console.print("Run [cyan]psa ops setup --url <url>[/cyan] first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

    try:
        nodes = client.list_nodes()
    except ApiError as e:
        console.print(f"[red]Failed to fetch nodes:[/red] {e}")
        raise typer.Exit(1)

    if not nodes:
        console.print("[dim]No nodes found[/dim]")
        return

    table = Table(title="Nodes")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Hostname")
    table.add_column("Status")
    table.add_column("OS")

    hostname = get_hostname()
    for node in nodes:
        # Mark current node
        name = node["name"]
        if node.get("hostname") == hostname:
            name = f"[green]{name} \u2713[/green]"

        status = node.get("status", "unknown")
        status_style = "green" if status == "Active" else "yellow"

        table.add_row(
            node["id"][:8] + "...",
            name,
            node.get("hostname", "-"),
            f"[{status_style}]{status}[/{status_style}]",
            node.get("os_type", "-"),
        )

    console.print(table)


@app.command(name="status")
def status() -> None:
    """Show PSA-OPS connection status"""
    config = get_config()

    console.print("[bold]PSA-OPS Configuration[/bold]\n")

    if not config.ops.is_configured():
        console.print("[yellow]Not configured[/yellow]")
        console.print("\nRun [cyan]psa ops setup --url <url>[/cyan] to configure")
        return

    console.print(f"Config file: [cyan]{CONFIG_PATH}[/cyan]")
    console.print(f"PSA-OPS URL: [cyan]{config.ops.url}[/cyan]")

    if config.ops.node_id:
        console.print(f"Node ID: [cyan]{config.ops.node_id[:8]}...[/cyan]")
    if config.ops.environment_name:
        console.print(f"Environment: [cyan]{config.ops.environment_name}[/cyan]")
    if config.ops.environment_id:
        console.print(f"Environment ID: [dim]{config.ops.environment_id[:8]}...[/dim]")

    # Test connection
    console.print("\n[bold]Connection Status[/bold]")
    client = ApiClient(config.ops.url)
    try:
        health = client.health()
        console.print(f"[green]\u2713[/green] Connected (v{health.get('version', '?')})")

        # Verify node still exists
        if config.ops.node_id:
            node = client.get_node_by_hostname(get_hostname())
            if node:
                console.print("[green]\u2713[/green] Node verified")
            else:
                console.print("[yellow]![/yellow] Node not found in PSA-OPS")
    except ApiError as e:
        console.print(f"[red]\u2717[/red] Connection failed: {e}")


def _resolve_api_domain_id(client: ApiClient, name: str, node_id: Optional[str] = None, domain_type: Optional[str] = None) -> str:
    """Resolve domain name to UUID via cache then PSA-OPS API."""
    cached = get_cached_domain_id(name)
    if cached:
        return cached
    domains = client.list_domains(name=name, node_id=node_id)
    if domain_type:
        domains = [d for d in domains if d.get("domain_type") == domain_type]
    if not domains:
        print_error(f"Domain '{name}' not found in PSA-OPS")
        raise typer.Exit(1)
    return domains[0]["id"]


@app.command(name="set-env")
def set_env(
    name: str = typer.Argument(..., help="Domain name (e.g. APPDOM)"),
    environment: str = typer.Argument(..., help="Environment name (e.g. dev, prod)"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type filter for disambiguation (app, prcs, web)",
    ),
) -> None:
    """
    Assign an environment to a domain in PSA-OPS

    Resolves domain and environment by name (no UUIDs needed).
    Domain is scoped to the current node.

    Examples:
        psa ops set-env APPDOM dev
        psa ops set-env APPDOM dev --type app
    """
    config = get_config()

    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

    # Resolve domain name -> UUID (scoped to this node)
    domain_id = _resolve_api_domain_id(client, name, node_id=config.ops.node_id, domain_type=domain_type)

    # Resolve environment name -> UUID
    env = client.resolve_environment(environment)
    if not env:
        print_error(f"Environment '{environment}' not found in PSA-OPS")
        raise typer.Exit(1)

    try:
        result = client.update_domain(domain_id, environment_id=env["id"])
        print_success(f"Domain {result.get('name', name)} assigned to environment '{environment}'")
    except ApiError as e:
        print_error(f"Failed to assign environment: {e}")
        raise typer.Exit(1)


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
def compare(
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
        psa ops compare APPDOM1 APPDOM2
        psa ops compare APPDOM1 APPDOM2 --type psappsrv.cfg
        psa ops compare APPDOM1 APPDOM2 APPDOM3 --all
    """
    if len(domains) < 2:
        print_error("At least 2 domain names required for comparison")
        raise typer.Exit(1)

    config = get_config()
    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
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
