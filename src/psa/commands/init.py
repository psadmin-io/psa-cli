"""Initialize psa configuration with PSA-OPS."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from psa.core.config import CONFIG_PATH, get_config
from psa.core.domain import DomainDiscovery

console = Console()


def standalone_setup(
    ps_cfg_home: Optional[str] = typer.Option(
        None,
        "--ps-cfg-home",
        "-c",
        help="PS_CFG_HOME path (auto-detected if not specified)",
    ),
    runtime_user: Optional[str] = typer.Option(
        None,
        "--runtime-user",
        "-u",
        help="Runtime user (default: psadm2)",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive mode, accept defaults",
    ),
) -> None:
    """
    Initialize psa in standalone mode

    Configures local paths and discovers domains.

    Examples:
        psa config setup                                    # Auto-detect paths
        psa config setup --ps-cfg-home /u01/app/psoft/cfg   # Explicit path
    """
    config = get_config()
    _init_standalone_mode(config, ps_cfg_home, runtime_user, non_interactive)


def ops_setup(
    url: str = typer.Option(
        ...,
        "--url",
        "-r",
        help="PSA-OPS URL (e.g., http://ops.psaops.local:8000)",
    ),
    environment_id: Optional[str] = typer.Option(
        None,
        "--environment-id",
        "-e",
        help="Environment ID (skips auto-detection)",
    ),
    role: Optional[str] = typer.Option(
        None,
        "--role",
        help="Node role: app, web, prcs, mid, webapp",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive mode, accept defaults",
    ),
    skip_domains: bool = typer.Option(
        False,
        "--skip-domains",
        help="Skip auto-registering domains after node setup",
    ),
) -> None:
    """
    Connect psa to PSA-OPS

    Registers this node with PSA-OPS, then registers locally-discovered
    domains. Use --skip-domains to register the node only.

    Examples:
        psa ops setup --url http://ops:8000
        psa ops setup --url http://ops:8000 --role app --yes
        psa ops setup --url http://ops:8000 --skip-domains
    """
    config = get_config()
    _init_ops_mode(config, url, environment_id, role, non_interactive, skip_domains)


def _detect_ps_paths_from_runtime_user(config, console) -> None:
    """Auto-detect PS paths from runtime user's environment via sudo."""
    import subprocess

    env_vars = ["PS_CFG_HOME", "PS_HOME", "PS_APP_HOME", "PS_CUST_HOME"]
    cmd = " && ".join(f'echo "{v}=${v}"' for v in env_vars)
    try:
        result = subprocess.run(
            ["sudo", "su", "-", config.runtime_user, "-c", cmd],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        for line in result.stdout.splitlines():
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip()
            if not val:
                continue
            path = Path(val)
            if key == "PS_CFG_HOME" and not config.ps_cfg_home:
                config.ps_cfg_home = path
                console.print(f"[green]✓[/green] Detected PS_CFG_HOME: {val}")
            elif key == "PS_HOME" and not config.ps_home:
                config.ps_home = path
                console.print(f"[green]✓[/green] Detected PS_HOME: {val}")
            elif key == "PS_APP_HOME" and not config.ps_app_home:
                config.ps_app_home = path
                console.print(f"[green]✓[/green] Detected PS_APP_HOME: {val}")
            elif key == "PS_CUST_HOME" and not config.ps_cust_home:
                config.ps_cust_home = path
                console.print(f"[green]✓[/green] Detected PS_CUST_HOME: {val}")
    except Exception:
        pass


def _init_standalone_mode(
    config,
    ps_cfg_home: Optional[str],
    runtime_user: Optional[str],
    non_interactive: bool,
) -> None:
    """Initialize in standalone mode (no PSA-OPS connection)."""
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
        elif config.sudo_enabled:
            _detect_ps_paths_from_runtime_user(config, console)
        if not config.ps_cfg_home and not non_interactive:
            path_input = Prompt.ask(
                "PS_CFG_HOME path",
                default=str(default_path),
            )
            config.ps_cfg_home = Path(path_input)

    # Configure runtime user
    if runtime_user:
        config.runtime_user = runtime_user
    elif not non_interactive:
        config.runtime_user = Prompt.ask(
            "Runtime user",
            default=config.runtime_user,
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
    console.print("  [cyan]psa domain list[/cyan]   List domains")
    console.print("  [cyan]psa domain status[/cyan] Check domain status")
    console.print("  [cyan]psa domain start[/cyan]  Start a domain")


def _init_ops_mode(
    config,
    ops_url: str,
    environment_id: Optional[str],
    role: Optional[str],
    non_interactive: bool,
    skip_domains: bool = False,
) -> None:
    """Initialize with PSA-OPS connection."""
    from psa.core.api import ApiClient, ApiError, get_hostname, get_ip_address

    hostname = get_hostname()
    console.print(f"[bold]Initializing psa for [cyan]{hostname}[/cyan][/bold]\n")

    # Test PSA-OPS connection
    console.print(f"Connecting to PSA-OPS: {ops_url}")
    client = ApiClient(ops_url)

    try:
        health = client.health()
        console.print(f"[green]✓[/green] PSA-OPS connected (v{health.get('version', '?')})\n")
    except ApiError as e:
        console.print(f"[red]✗[/red] PSA-OPS connection failed: {e}")
        raise typer.Exit(1)

    # Fetch environments
    try:
        environments = client.list_environments()
    except ApiError as e:
        console.print(f"[red]✗[/red] Failed to fetch environments: {e}")
        raise typer.Exit(1)

    if not environments:
        console.print("[red]✗[/red] No environments found in PSA-OPS")
        console.print("Create an environment in the PSA-OPS UI first")
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

    valid_roles = ["app", "web", "prcs", "mid", "webapp"]
    if role and role in valid_roles:
        ps_role = role
    elif non_interactive:
        console.print("[red]✗[/red] Node role required in non-interactive mode")
        console.print("Use --role [app|web|prcs|mid|webapp]")
        raise typer.Exit(1)
    else:
        ps_role = Prompt.ask(
            "Role",
            choices=valid_roles,
            default="app",
        )

    # Check if node exists
    node = client.get_node_by_hostname(hostname)
    if node:
        console.print(f"[green]✓[/green] Node already registered: {node['id'][:8]}...")
        node_id = node["id"]
        # Update role if it differs from what's in the API
        if ps_role and node.get("ps_role") != ps_role:
            try:
                client.update_node(node_id, ps_role=ps_role)
                console.print(f"[green]✓[/green] Role updated to [cyan]{ps_role}[/cyan]")
            except ApiError as e:
                console.print(f"[yellow]![/yellow] Failed to update role: {e}")
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

    if skip_domains:
        return

    from psa.commands.ops import _register_domains
    from psa.core.output import print_info, print_warning

    console.print("\n[bold]Registering domains[/bold]")
    try:
        _register_domains(config, client, force=non_interactive, json_output=False)
    except typer.Exit:
        print_warning("Domain registration failed — run 'psa ops register' to retry")
    except typer.Abort:
        print_info("Domain registration skipped — run 'psa ops register' later")
