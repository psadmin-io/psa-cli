"""PSA-OPS management commands."""

import json
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.commands import init
from psa.core.config import CONFIG_PATH, PsaConfig, get_config
from psa.core.domain import DomainDiscovery, DomainInfo
from psa.core.domain_cache import get_cached_domain_id, update_cache_from_ingest
from psa.core.output import (
    apply_verbosity,
    print_error,
    print_info,
    print_success,
    print_warning,
    run_step,
)
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
    cached = get_cached_domain_id(name, domain_type=domain_type)
    if cached:
        return cached
    domains = client.list_domains(name=name, node_id=node_id)
    if domain_type:
        domains = [d for d in domains if (d.get("type") or d.get("domain_type")) == domain_type]
    if not domains:
        print_error(f"Domain '{name}' not found in PSA-OPS")
        print_info("Run 'psa ops register' to push locally-discovered domains to PSA-OPS")
        raise typer.Exit(1)
    return domains[0]["id"]


def _discover_and_filter(names: Optional[List[str]]) -> List[DomainInfo]:
    """Run discovery and optionally filter to a subset of domain names.

    A single name may match multiple DomainInfo entries when the same name
    exists across types (e.g. IHDEV/app + IHDEV/prcs + IHDEV/web). All
    matches are returned.
    """
    config = get_config()
    discovery = DomainDiscovery(config)
    domains = discovery.discover_all()

    if names:
        requested = set(names)
        matched = [d for d in domains if d.name in requested]
        found = {d.name for d in matched}
        missing = [n for n in names if n not in found]
        if missing:
            print_error(f"Domain(s) not found locally: {', '.join(missing)}")
            raise typer.Exit(1)
        return matched

    return domains


def _register_domains(
    config: PsaConfig,
    client: ApiClient,
    *,
    names: Optional[List[str]] = None,
    force: bool = False,
    json_output: bool = False,
) -> int:
    """Discover local domains and push to PSA-OPS via ingest_scan.

    Returns the number of domains registered. Idempotent — server upserts.
    """
    if json_output:
        domains = _discover_and_filter(names)
    else:
        domains = run_step("Discovering domains", lambda: _discover_and_filter(names))

    if not domains:
        if not json_output:
            print_warning("No domains found to register")
        else:
            console.print_json(json.dumps({"hostname": get_hostname(), "environment_id": config.ops.environment_id, "registered": []}))
        return 0

    if not force and not json_output:
        table = Table(title="Register targets")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("DB", style="dim")
        for d in domains:
            table.add_row(d.name, d.domain_type, (d.config or {}).get("db_name", "-"))
        console.print(table)
        if not typer.confirm(f"Register {len(domains)} domain(s) with PSA-OPS?", default=True):
            raise typer.Abort()

    hostname = get_hostname()

    def _do_ingest() -> dict:
        return client.ingest_scan(
            hostname=hostname,
            domains=[d.to_dict() for d in domains],
            environment_id=config.ops.environment_id,
        )

    try:
        if json_output:
            result = _do_ingest()
        else:
            result = run_step("Registering domains", _do_ingest)
    except ApiError as e:
        print_error(f"Registration failed: {e}")
        raise typer.Exit(1)

    if result.get("domains"):
        update_cache_from_ingest(result)

    registered = result.get("domains", [])
    if json_output:
        console.print_json(json.dumps({
            "hostname": hostname,
            "environment_id": config.ops.environment_id,
            "registered": [
                {"name": d.get("name"), "id": d.get("id"), "domain_type": d.get("type") or d.get("domain_type")}
                for d in registered
            ],
        }))
    else:
        print_success(f"Registered {len(registered)} domain(s) with PSA-OPS")

    return len(registered)


@app.command(name="register")
def register(
    names: Optional[List[str]] = typer.Argument(None, help="Domain names (omit for all)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """
    Push locally-discovered domains to PSA-OPS

    Discovers domains on this node and registers them with PSA-OPS using the
    node's anchor environment. Idempotent — re-running upserts.

    Examples:
        psa ops register                    # all discovered domains
        psa ops register APPDOM             # just one
        psa ops register APPDOM PRCSDOM     # subset
        psa ops register --yes              # non-interactive
    """
    apply_verbosity(quiet, verbose)
    config = get_config()

    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)
    _register_domains(config, client, names=names, force=yes, json_output=json_output)


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


def _resolve_domain_id(client: ApiClient, name: str, domain_type: Optional[str] = None) -> str:
    """Resolve domain name to UUID. Checks local cache first, then PSA-OPS."""
    cached = get_cached_domain_id(name, domain_type=domain_type)
    if cached:
        return cached
    if domain_type:
        candidates = client.list_domains(name=name)
        candidates = [
            d for d in candidates
            if (d.get("type") or d.get("domain_type") or "").lower() == domain_type.lower()
        ]
        if candidates:
            return candidates[0]["id"]
    else:
        domain = client.resolve_domain(name)
        if domain:
            return domain["id"]
    print_error(f"Domain '{name}' not found in PSA-OPS")
    print_info("Run 'psa ops register' to push locally-discovered domains to PSA-OPS")
    raise typer.Exit(1)


@app.command(name="compare")
def compare(
    domains: List[str] = typer.Argument(
        ...,
        help="Domain names to compare (at least 2)",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, web) — disambiguates same-named domains and auto-picks the primary config",
    ),
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Specific config file (default: primary for --type, e.g. psappsrv.cfg for app)",
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
        psa ops compare ihlab ihdev --type app
        psa ops compare ihlab ihdev --type app --config psworker.cfg
        psa ops compare APPDOM1 APPDOM2 APPDOM3 --all
    """
    from psa.core.compare import get_primary_config

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
        domain_id = _resolve_domain_id(client, name, domain_type=domain_type)
        domain_ids.append(domain_id)

    # Pick config file: explicit --config wins, else infer from --type
    resolved_config = config_file or (get_primary_config(domain_type) if domain_type else None)

    try:
        result = client.compare_configs(domain_ids, resolved_config)
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
