"""OPS management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.core.config import CONFIG_PATH, get_config
from psa.core.domain import DomainDiscovery
from psa.core.output import print_error, print_success
from psa.core.api import ApiClient, ApiError, get_hostname, get_ip_address

console = Console()

app = typer.Typer(
    name="ops",
    help="Manage OPS API connection and data",
    no_args_is_help=True,
)


@app.command(name="status")
def status() -> None:
    """Show OPS API configuration and connection status."""
    config = get_config()

    console.print("[bold]OPS Configuration[/bold]\n")

    if not config.ops.is_configured():
        console.print("[yellow]Not configured[/yellow]")
        console.print("\nRun [cyan]psa init --ops-url <url>[/cyan] to configure")
        return

    console.print(f"Config file: [cyan]{CONFIG_PATH}[/cyan]")
    console.print(f"OPS URL: [cyan]{config.ops.url}[/cyan]")

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
        console.print(f"[green]✓[/green] Connected (v{health.get('version', '?')})")

        # Verify node still exists
        if config.ops.node_id:
            node = client.get_node_by_hostname(get_hostname())
            if node:
                console.print("[green]✓[/green] Node verified")
            else:
                console.print("[yellow]![/yellow] Node not found in OPS")
    except ApiError as e:
        console.print(f"[red]✗[/red] Connection failed: {e}")


@app.command(name="environments")
def list_environments() -> None:
    """List environments from OPS API."""
    config = get_config()

    if not config.ops.is_configured():
        console.print("[red]OPS not configured[/red]")
        console.print("Run [cyan]psa init --ops-url <url>[/cyan] first")
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
            name = f"[green]{name} ✓[/green]"

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
    """List nodes from OPS API."""
    config = get_config()

    if not config.ops.is_configured():
        console.print("[red]OPS not configured[/red]")
        console.print("Run [cyan]psa init --ops-url <url>[/cyan] first")
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
            name = f"[green]{name} ✓[/green]"

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


@app.command(name="register")
def register(
    environment_id: Optional[str] = typer.Option(
        None,
        "--environment-id",
        "-e",
        help="Environment ID (uses saved config if not provided)",
    ),
) -> None:
    """Register or re-register this node with OPS."""
    config = get_config()
    hostname = get_hostname()

    if not config.ops.is_configured():
        console.print("[red]OPS not configured[/red]")
        console.print("Run [cyan]psa init --ops-url <url>[/cyan] first")
        raise typer.Exit(1)

    env_id = environment_id or config.ops.environment_id
    if not env_id:
        console.print("[red]No environment ID[/red]")
        console.print("Use --environment-id or run [cyan]psa init[/cyan] first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

    # Check if node exists
    existing = client.get_node_by_hostname(hostname)
    if existing:
        console.print(f"[yellow]Node already registered:[/yellow] {existing['id'][:8]}...")
        console.print("To update, use the OPS UI")
        return

    # Create node
    ip_address = get_ip_address()
    console.print(f"Registering node [cyan]{hostname}[/cyan] ({ip_address})...")
    try:
        node = client.create_node(
            name=hostname,
            hostname=hostname,
            ip_address=ip_address,
            environment_id=env_id,
        )
        console.print(f"[green]✓[/green] Node registered: {node['id'][:8]}...")

        # Update config
        config.ops.node_id = node["id"]
        config.save()
        console.print("[green]✓[/green] Configuration updated")
    except ApiError as e:
        console.print(f"[red]✗[/red] Registration failed: {e}")
        raise typer.Exit(1)


@app.command(name="sync")
def sync(
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Discover domains and sync to OPS API.

    Alias for 'psa discover --push'. Discovers local domains
    and pushes them to the configured OPS API.

    Examples:
        psa ops sync
        psa ops sync --type app
    """
    config = get_config()
    hostname = get_hostname()

    if not config.ops.is_configured():
        print_error("OPS not configured. Run 'psa init' first")
        raise typer.Exit(1)

    # Discover domains
    console.print("Discovering domains...")
    discovery = DomainDiscovery(config)

    try:
        if domain_type:
            domain_type = domain_type.lower()
            if domain_type == "app":
                domains = discovery.discover_appserver_domains()
            elif domain_type == "prcs":
                domains = discovery.discover_prcs_domains()
            elif domain_type == "pia":
                domains = discovery.discover_pia_domains()
            else:
                print_error(f"Unknown domain type: {domain_type}")
                raise typer.Exit(1)
        else:
            domains = discovery.discover_all()
    except Exception as e:
        print_error(f"Discovery failed: {e}")
        raise typer.Exit(1)

    if not domains:
        console.print("[dim]No domains found[/dim]")
        return

    console.print(f"[green]✓[/green] Found {len(domains)} domain(s)")

    # Push to API
    console.print(f"Syncing to {config.ops.url}...")
    client = ApiClient(config.ops.url)

    domain_dicts = [d.to_dict() for d in domains]

    try:
        result = client.ingest_scan(
            hostname=hostname,
            domains=domain_dicts,
            environment_id=config.ops.environment_id,
        )

        if result.get("errors"):
            for error in result["errors"]:
                print_error(error)
            raise typer.Exit(1)

        created = result.get("domains_created", 0)
        updated = result.get("domains_updated", 0)
        unchanged = result.get("domains_unchanged", 0)
        configs = result.get("configs_created", 0)
        msg = f"Synced: {created} created, {updated} updated, {unchanged} unchanged"
        if configs:
            msg += f", {configs} config versions"
        print_success(msg)

    except ApiError as e:
        print_error(f"Sync failed: {e}")
        raise typer.Exit(1)
