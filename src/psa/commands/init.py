"""Initialize psa configuration."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from psa.core.config import CONFIG_PATH, get_config
from psa.core.domain import DomainDiscovery

console = Console()


def init(
    ops_url: Optional[str] = typer.Option(
        None,
        "--ops-url",
        "-r",
        help="OPS API URL (e.g., http://ops.psaops.local:8000). If omitted, runs in standalone mode.",
    ),
    ps_cfg_home: Optional[str] = typer.Option(
        None,
        "--ps-cfg-home",
        "-c",
        help="PS_CFG_HOME path (auto-detected if not specified)",
    ),
    domain_user: Optional[str] = typer.Option(
        None,
        "--domain-user",
        "-u",
        help="Domain user (default: psadm2)",
    ),
    environment_id: Optional[str] = typer.Option(
        None,
        "--environment-id",
        "-e",
        help="Environment ID (ops mode only, skips auto-detection)",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive mode, accept defaults",
    ),
) -> None:
    """
    Initialize psa configuration.

    Standalone mode (no --ops-url):
        Configures local paths and discovers domains.

    OPS mode (with --ops-url):
        Connects to OPS API, registers node, and saves connection config.

    Examples:
        psa init                                    # Standalone, auto-detect paths
        psa init --ps-cfg-home /u01/app/psoft/cfg   # Standalone, explicit path
        psa init --ops-url http://ops:8000          # OPS mode
    """
    config = get_config()

    if ops_url:
        _init_ops_mode(config, ops_url, environment_id, non_interactive)
    else:
        _init_standalone_mode(config, ps_cfg_home, domain_user, non_interactive)


def _init_standalone_mode(
    config,
    ps_cfg_home: Optional[str],
    domain_user: Optional[str],
    non_interactive: bool,
) -> None:
    """Initialize in standalone mode (no OPS connection)."""
    console.print("[bold]Initializing psa (standalone mode)[/bold]\n")

    # Configure PS_CFG_HOME
    if ps_cfg_home:
        config.ps_cfg_home = Path(ps_cfg_home)
    elif not config.ps_cfg_home:
        # Try to auto-detect
        default_path = config.ps_base / "cfg"
        if default_path.exists():
            config.ps_cfg_home = default_path
            console.print(f"[green]✓[/green] Auto-detected PS_CFG_HOME: {default_path}")
        elif not non_interactive:
            path_input = Prompt.ask(
                "PS_CFG_HOME path",
                default=str(default_path),
            )
            config.ps_cfg_home = Path(path_input)

    # Configure domain user
    if domain_user:
        config.domain_user = domain_user
    elif not non_interactive:
        config.domain_user = Prompt.ask(
            "Domain user",
            default=config.domain_user,
        )

    # Discover domains
    console.print("\nDiscovering domains...")
    discovery = DomainDiscovery(config)
    try:
        domains = discovery.discover_all()
        if domains:
            console.print(f"[green]✓[/green] Found {len(domains)} domain(s):")
            for d in domains:
                console.print(f"  [cyan]{d.name}[/cyan] ({d.domain_type})")
        else:
            console.print("[dim]No domains found[/dim]")
    except Exception as e:
        console.print(f"[yellow]![/yellow] Discovery failed: {e}")

    # Save config
    config.save()
    console.print(f"\n[green]✓[/green] Configuration saved to [cyan]{CONFIG_PATH}[/cyan]")

    console.print("\nYou can now use:")
    console.print("  [cyan]psa discover[/cyan]      List domains")
    console.print("  [cyan]psa domain status[/cyan] Check domain status")
    console.print("  [cyan]psa domain start[/cyan]  Start a domain")
    console.print("\nTo connect to OPS later:")
    console.print("  [cyan]psa init --ops-url http://ops:8000[/cyan]")


def _init_ops_mode(
    config,
    ops_url: str,
    environment_id: Optional[str],
    non_interactive: bool,
) -> None:
    """Initialize with OPS API connection."""
    from psa.core.api import ApiClient, ApiError, get_hostname, get_ip_address

    hostname = get_hostname()
    console.print(f"[bold]Initializing psa for [cyan]{hostname}[/cyan][/bold]\n")

    # Test OPS connection
    console.print(f"Connecting to OPS: {ops_url}")
    client = ApiClient(ops_url)

    try:
        health = client.health()
        console.print(f"[green]✓[/green] OPS connected (v{health.get('version', '?')})\n")
    except ApiError as e:
        console.print(f"[red]✗[/red] OPS connection failed: {e}")
        raise typer.Exit(1)

    # Fetch environments
    try:
        environments = client.list_environments()
    except ApiError as e:
        console.print(f"[red]✗[/red] Failed to fetch environments: {e}")
        raise typer.Exit(1)

    if not environments:
        console.print("[red]✗[/red] No environments found in OPS")
        console.print("Create an environment in the OPS UI first")
        raise typer.Exit(1)

    # Build environment lookup by db_name
    env_by_db = {}
    for env in environments:
        if db_name := env.get("db_name"):
            env_by_db[db_name.upper()] = env

    # Discover domains to detect environment
    detected_env = None
    if not environment_id:
        console.print("Discovering domains...")
        discovery = DomainDiscovery(config)
        try:
            domains = discovery.discover_all()
            if domains:
                console.print(f"[green]✓[/green] Found {len(domains)} domain(s)\n")

                # Try to match db_name
                for domain in domains:
                    if domain.config and (db_name := domain.config.get("db_name")):
                        db_name = db_name.upper()
                        if db_name in env_by_db:
                            detected_env = env_by_db[db_name]
                            console.print(
                                f"[green]✓[/green] Detected environment: "
                                f"[cyan]{detected_env['name']}[/cyan] "
                                f"(from db_name: {db_name})"
                            )
                            break
            else:
                console.print("[dim]No domains found[/dim]\n")
        except Exception as e:
            console.print(f"[yellow]![/yellow] Discovery failed: {e}\n")

    # Select environment
    selected_env = None

    if environment_id:
        # Use provided environment ID
        for env in environments:
            if env["id"] == environment_id:
                selected_env = env
                break
        if not selected_env:
            console.print(f"[red]✗[/red] Environment not found: {environment_id}")
            raise typer.Exit(1)
    elif detected_env:
        # Confirm detected environment
        if non_interactive:
            selected_env = detected_env
        else:
            if Confirm.ask(f"Use [cyan]{detected_env['name']}[/cyan]?", default=True):
                selected_env = detected_env

    if not selected_env:
        # Show environment list and prompt
        console.print("\n[bold]Available environments:[/bold]")
        table = Table(show_header=True)
        table.add_column("#", style="dim")
        table.add_column("Name")
        table.add_column("Pillar")
        table.add_column("Tier")
        table.add_column("DB Name")

        for i, env in enumerate(environments, 1):
            table.add_row(
                str(i),
                env["name"],
                env.get("pillar", "-"),
                env.get("tier", "-"),
                env.get("db_name", "-"),
            )
        console.print(table)

        if non_interactive:
            console.print("[red]✗[/red] Cannot select environment in non-interactive mode")
            console.print("Use --environment-id to specify")
            raise typer.Exit(1)

        choice = Prompt.ask(
            "Select environment",
            choices=[str(i) for i in range(1, len(environments) + 1)],
        )
        selected_env = environments[int(choice) - 1]

    console.print(f"\n[green]✓[/green] Using environment: [cyan]{selected_env['name']}[/cyan]")

    # Prompt for node-level facts
    console.print("\n[bold]Node configuration:[/bold]")

    if non_interactive:
        console.print("[red]✗[/red] Node facts required in non-interactive mode")
        console.print("Role must be specified")
        raise typer.Exit(1)

    ps_role = Prompt.ask(
        "Role",
        choices=["app", "web", "prcs", "mid", "webapp"],
        default="app",
    )

    # Check if node exists
    node = client.get_node_by_hostname(hostname)
    if node:
        console.print(f"[green]✓[/green] Node already registered: {node['id'][:8]}...")
        node_id = node["id"]
    else:
        # Register node
        ip_address = get_ip_address()
        console.print(f"Registering node [cyan]{hostname}[/cyan] ({ip_address})...")
        try:
            node = client.create_node(
                name=hostname,
                hostname=ip_address,
                environment_id=selected_env["id"],
                ps_role=ps_role,
            )
            node_id = node["id"]
            console.print(f"[green]✓[/green] Node registered: {node_id[:8]}...")
        except ApiError as e:
            console.print(f"[red]✗[/red] Failed to register node: {e}")
            raise typer.Exit(1)

    # Save config
    config.ops.url = ops_url
    config.ops.node_id = node_id
    config.ops.environment_id = selected_env["id"]
    config.ops.environment_name = selected_env["name"]
    config.ops.tier = selected_env.get("tier")
    config.ops.pillar = selected_env.get("pillar")
    config.ops.zone = selected_env.get("zone")
    config.ops.ps_role = ps_role
    config.save()

    console.print(f"\n[green]✓[/green] Configuration saved to [cyan]{CONFIG_PATH}[/cyan]")

    tier_str = selected_env.get("tier") or "-"
    pillar_str = selected_env.get("pillar") or "-"
    zone_str = selected_env.get("zone") or "-"
    console.print(
        f"[green]✓[/green] Facts: pillar={pillar_str}, tier={tier_str}, zone={zone_str}, role={ps_role}"
    )

    console.print("\nYou can now use:")
    console.print("  [cyan]psa discover --push[/cyan]  Push domains to OPS")
    console.print("  [cyan]psa ops status[/cyan]       Check connection status")
