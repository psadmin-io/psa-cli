"""Domain management commands."""

import json
import urllib.error
import urllib.request
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.core.config import get_config
from psa.core.domain import DomainDiscovery, DomainInfo
from psa.core.domain_cache import get_cached_domain_id
from psa.core.api import ApiClient, ApiError
from psa.core.output import print_error, print_info, print_success, print_warning
from psa.core.psadmin import PsadminExecutor, PsadminResult

console = Console()

app = typer.Typer(
    name="domain",
    help="Manage PeopleSoft domains (start, stop, status, list)",
    no_args_is_help=True,
)


def _find_domain(name: str, domain_type: Optional[str] = None) -> Optional[DomainInfo]:
    """Find a domain by name."""
    config = get_config()
    discovery = DomainDiscovery(config)
    return discovery.find_domain(name, domain_type)


def _get_executor() -> PsadminExecutor:
    """Get a psadmin executor instance."""
    return PsadminExecutor(get_config())


def _execute_domain_command(
    domain: DomainInfo,
    action: str,
    executor: PsadminExecutor,
) -> PsadminResult:
    """Execute a domain command based on domain type."""
    method_map = {
        "app": {
            "status": executor.app_status,
            "start": executor.app_start,
            "stop": executor.app_stop,
            "kill": executor.app_kill,
            "configure": executor.app_configure,
            "purge": executor.app_purge,
            "flush": executor.app_flush,
        },
        "prcs": {
            "status": executor.prcs_status,
            "start": executor.prcs_start,
            "stop": executor.prcs_stop,
            "kill": executor.prcs_kill,
            "configure": executor.prcs_configure,
            "purge": executor.prcs_purge,
            "flush": executor.prcs_flush,
        },
        "pia": {
            "status": executor.web_status,
            "start": executor.web_start,
            "stop": executor.web_stop,
            "kill": executor.web_kill,
            "purge": executor.web_purge,
        },
    }

    type_methods = method_map.get(domain.domain_type, {})
    method = type_methods.get(action)

    if not method:
        return PsadminResult(
            success=False,
            exit_code=1,
            output=f"Action '{action}' not supported for domain type '{domain.domain_type}'",
            command="",
        )

    return method(domain.name, domain.ps_cfg_home)


def _report_status_to_api(name: str, status_str: str) -> None:
    """Report domain status to OPS API. Never fails the command."""
    status_map = {"running": "Running", "stopped": "Stopped"}
    api_status = status_map.get(status_str, "Unknown")

    config = get_config()
    if not config.ops.is_configured():
        print_warning("OPS not configured; skipping report")
        return

    domain_id = get_cached_domain_id(name)
    if not domain_id:
        print_warning(f"No cached domain ID for '{name}'; run `psa discover --report` first")
        return

    try:
        client = ApiClient(config.ops.url)
        client.update_domain(domain_id, status=api_status)
        console.print("[dim]\u2191 reported[/dim]")
    except Exception as e:
        print_warning(f"report failed: {e}")


def _parse_status_output(output: str, domain_type: str) -> str:
    """Parse psadmin status output to determine running/stopped status."""
    output_lower = output.lower()

    if domain_type == "app":
        # Check for running indicators
        if "processes running" in output_lower or "server status: active" in output_lower:
            return "running"
        if "not booted" in output_lower or "no processes" in output_lower:
            return "stopped"
    elif domain_type == "prcs":
        if "process scheduler is running" in output_lower:
            return "running"
        if "not running" in output_lower or "no process" in output_lower:
            return "stopped"
    elif domain_type == "pia":
        if "running" in output_lower and "not running" not in output_lower:
            return "running"
        if "stopped" in output_lower or "not running" in output_lower:
            return "stopped"

    return "unknown"


def _format_status_json(domain: DomainInfo, result: PsadminResult) -> dict:
    """Format status result as structured JSON."""
    status = _parse_status_output(result.output, domain.domain_type)
    return {
        "name": domain.name,
        "type": domain.domain_type,
        "path": str(domain.path),
        "ps_cfg_home": str(domain.ps_cfg_home) if domain.ps_cfg_home else None,
        "status": status,
        "success": result.success,
        "exit_code": result.exit_code,
        "raw_output": result.output,
    }


@app.command("list")
def list_domains(
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by domain type (app, prcs, pia)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
) -> None:
    """List all domains."""
    from psa.commands.discover import discover
    discover(json_output=json_output, domain_type=domain_type)


@app.command("status")
def status(
    name: str = typer.Argument(..., help="Domain name"),
    full: bool = typer.Option(
        False,
        "--full",
        "-f",
        help="Show full raw psadmin output",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as structured JSON",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia) - auto-detected if not specified",
    ),
    report: bool = typer.Option(
        False,
        "--report",
        "-r",
        help="Report status to OPS API",
    ),
) -> None:
    """
    Show status of a domain.

    Examples:
        psa domain status APPDOM           # Short output (running/stopped)
        psa domain status APPDOM --full    # Full psadmin output
        psa domain status APPDOM --json    # Structured JSON
        psa domain status APPDOM --report  # Report status to OPS
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    executor = _get_executor()
    result = _execute_domain_command(domain, "status", executor)

    status_str = _parse_status_output(result.output, domain.domain_type)

    if json_output:
        console.print_json(json.dumps(_format_status_json(domain, result)))
    elif full:
        console.print(result.output)
    else:
        # Short output
        if status_str == "running":
            console.print(f"[green]{name}[/green]: [bold green]running[/bold green]")
        elif status_str == "stopped":
            console.print(f"[yellow]{name}[/yellow]: [bold yellow]stopped[/bold yellow]")
        else:
            console.print(f"[dim]{name}[/dim]: [dim]unknown[/dim]")

    if report:
        _report_status_to_api(name, status_str)


@app.command("start")
def start(
    name: str = typer.Argument(..., help="Domain name"),
    serial: bool = typer.Option(
        False,
        "--serial",
        "-s",
        help="Start processes serially (disable parallel boot)",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Start a domain.

    Examples:
        psa domain start APPDOM
        psa domain start PRCSDOM --serial
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    # Temporarily disable parallel boot if serial requested
    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    print_info(f"Starting {domain.domain_type} domain: {name}")
    result = _execute_domain_command(domain, "start", executor)

    if result.success:
        print_success(f"Domain {name} started")
    else:
        print_error(f"Failed to start domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("stop")
def stop(
    name: str = typer.Argument(..., help="Domain name"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force stop (kill processes)",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Stop a domain.

    Examples:
        psa domain stop APPDOM
        psa domain stop PRCSDOM --force
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    executor = _get_executor()
    action = "kill" if force else "stop"

    print_info(f"Stopping {domain.domain_type} domain: {name}")
    result = _execute_domain_command(domain, action, executor)

    if result.success:
        print_success(f"Domain {name} stopped")
    else:
        print_error(f"Failed to stop domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("restart")
def restart(
    name: str = typer.Argument(..., help="Domain name"),
    serial: bool = typer.Option(
        False,
        "--serial",
        "-s",
        help="Start processes serially",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Restart a domain (stop then start).

    Examples:
        psa domain restart APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    print_info(f"Restarting {domain.domain_type} domain: {name}")

    # Stop
    result = _execute_domain_command(domain, "stop", executor)
    if not result.success:
        print_warning(f"Stop returned non-zero: {result.output}")

    # Start
    result = _execute_domain_command(domain, "start", executor)
    if result.success:
        print_success(f"Domain {name} restarted")
    else:
        print_error(f"Failed to start domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("kill")
def kill(
    name: str = typer.Argument(..., help="Domain name"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Force stop a domain (kill processes).

    Examples:
        psa domain kill APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    executor = _get_executor()
    print_info(f"Force stopping {domain.domain_type} domain: {name}")
    result = _execute_domain_command(domain, "kill", executor)

    if result.success:
        print_success(f"Domain {name} killed")
    else:
        print_error(f"Failed to kill domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("configure")
def configure(
    name: str = typer.Argument(..., help="Domain name"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Configure a domain.

    Examples:
        psa domain configure APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    if domain.domain_type == "pia":
        print_error("Configure not supported for PIA domains")
        raise typer.Exit(1)

    executor = _get_executor()
    print_info(f"Configuring {domain.domain_type} domain: {name}")
    result = _execute_domain_command(domain, "configure", executor)

    if result.success:
        print_success(f"Domain {name} configured")
    else:
        print_error(f"Failed to configure domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("purge")
def purge(
    name: str = typer.Argument(..., help="Domain name"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Clear domain cache.

    Examples:
        psa domain purge APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    executor = _get_executor()
    print_info(f"Purging cache for {domain.domain_type} domain: {name}")
    result = _execute_domain_command(domain, "purge", executor)

    if result.success:
        print_success(f"Domain {name} cache purged")
    else:
        print_error(f"Failed to purge cache: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("flush")
def flush(
    name: str = typer.Argument(..., help="Domain name"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs)",
    ),
) -> None:
    """
    Clear domain IPC resources.

    Examples:
        psa domain flush APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    if domain.domain_type == "pia":
        print_warning("Flush not applicable for PIA domains")
        return

    executor = _get_executor()
    print_info(f"Flushing IPC for {domain.domain_type} domain: {name}")
    result = _execute_domain_command(domain, "flush", executor)

    if result.success:
        print_success(f"Domain {name} IPC flushed")
    else:
        print_error(f"Failed to flush IPC: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("bounce")
def bounce(
    name: str = typer.Argument(..., help="Domain name"),
    serial: bool = typer.Option(
        False,
        "--serial",
        "-s",
        help="Start processes serially",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
) -> None:
    """
    Full domain bounce (stop, purge, flush, configure, start).

    Examples:
        psa domain bounce APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    print_info(f"Bouncing {domain.domain_type} domain: {name}")

    # Stop
    console.print("  [dim]Stopping...[/dim]")
    result = _execute_domain_command(domain, "stop", executor)

    # Purge
    console.print("  [dim]Purging cache...[/dim]")
    _execute_domain_command(domain, "purge", executor)

    # Flush (skip for PIA)
    if domain.domain_type != "pia":
        console.print("  [dim]Flushing IPC...[/dim]")
        _execute_domain_command(domain, "flush", executor)

    # Configure (skip for PIA)
    if domain.domain_type != "pia":
        console.print("  [dim]Configuring...[/dim]")
        _execute_domain_command(domain, "configure", executor)

    # Start
    console.print("  [dim]Starting...[/dim]")
    result = _execute_domain_command(domain, "start", executor)

    if result.success:
        print_success(f"Domain {name} bounced")
    else:
        print_error(f"Failed to start domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("reconfigure")
def reconfigure(
    name: str = typer.Argument(..., help="Domain name"),
    serial: bool = typer.Option(
        False,
        "--serial",
        "-s",
        help="Start processes serially",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs)",
    ),
) -> None:
    """
    Reconfigure domain (stop, configure, start).

    Examples:
        psa domain reconfigure APPDOM
    """
    domain = _find_domain(name, domain_type)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    if domain.domain_type == "pia":
        print_error("Reconfigure not supported for PIA domains")
        raise typer.Exit(1)

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    print_info(f"Reconfiguring {domain.domain_type} domain: {name}")

    # Stop
    console.print("  [dim]Stopping...[/dim]")
    _execute_domain_command(domain, "stop", executor)

    # Configure
    console.print("  [dim]Configuring...[/dim]")
    _execute_domain_command(domain, "configure", executor)

    # Start
    console.print("  [dim]Starting...[/dim]")
    result = _execute_domain_command(domain, "start", executor)

    if result.success:
        print_success(f"Domain {name} reconfigured")
    else:
        print_error(f"Failed to start domain: {result.output}")
        raise typer.Exit(result.exit_code)


@app.command("set-env")
def set_env(
    domain_id: str = typer.Argument(..., help="Domain ID (from PSA-OPS)"),
    environment_id: str = typer.Argument(..., help="Environment ID to assign"),
    ops_url: Optional[str] = typer.Option(
        None,
        "--ops-url",
        envvar="PSA_OPS_URL",
        help="OPS API URL (or uses saved config from psa init)",
    ),
) -> None:
    """
    Assign an environment to a domain in PSA-OPS.

    Examples:
        psa domain set-env abc123 def456
        psa domain set-env abc123 def456 --ops-url http://ops:8002
    """
    config = get_config()

    effective_ops_url = ops_url
    if not effective_ops_url:
        if config.ops.is_configured():
            effective_ops_url = config.ops.url
        else:
            print_error("OPS not configured. Run 'psa init' first or use --ops-url")
            raise typer.Exit(1)

    url = f"{effective_ops_url.rstrip('/')}/api/v1/domains/{domain_id}"
    payload = {"environment_id": environment_id}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            print_success(f"Domain {result.get('name', domain_id)} assigned to environment")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        try:
            error_data = json.loads(error_body)
            print_error(error_data.get("detail", str(e)))
        except json.JSONDecodeError:
            print_error(f"HTTP {e.code}: {error_body or str(e)}")
        raise typer.Exit(1)
    except urllib.error.URLError as e:
        print_error(f"Connection failed: {e.reason}")
        raise typer.Exit(1)


def _resolve_api_domain_id(client: ApiClient, name: str) -> str:
    """Resolve domain name to UUID via cache then OPS API."""
    cached = get_cached_domain_id(name)
    if cached:
        return cached
    domain = client.resolve_domain(name)
    if not domain:
        print_error(f"Domain '{name}' not found in OPS")
        raise typer.Exit(1)
    return domain["id"]


@app.command("drift")
def drift(
    name: str = typer.Argument(..., help="Domain name"),
    config_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Config type for detailed drift (e.g. psappsrv.cfg)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
) -> None:
    """
    Show config drift for a domain.

    Without --type: shows drift summary across all config types.
    With --type: shows detailed key-level changes for that config type.

    Examples:
        psa domain drift APPDOM
        psa domain drift APPDOM --type psappsrv.cfg
    """
    config = get_config()
    if not config.ops.is_configured():
        print_error("OPS not configured. Run 'psa init' first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)
    domain_id = _resolve_api_domain_id(client, name)

    try:
        if config_type:
            result = client.get_domain_drift(domain_id, config_type)
        else:
            result = client.get_drift_summary(domain_id)
    except ApiError as e:
        print_error(f"Drift check failed: {e}")
        raise typer.Exit(1)

    if json_output:
        console.print_json(json.dumps(result, default=str, indent=2))
        return

    if config_type:
        # Detailed drift for a specific config type
        changes = result.get("changes", [])
        if not changes:
            console.print(f"[green]No drift detected for {config_type}[/green]")
            return

        table = Table(title=f"Drift: {name} ({config_type})")
        table.add_column("Key", style="cyan")
        table.add_column("Previous", style="red")
        table.add_column("Current", style="green")
        table.add_column("Change", style="dim")

        for change in changes:
            change_type = change.get("change_type", "")
            style = "yellow"
            if change_type == "added":
                style = "green"
            elif change_type == "removed":
                style = "red"

            old_val = str(change.get("old_value", "")) if change.get("old_value") is not None else "[dim]-[/dim]"
            new_val = str(change.get("new_value", "")) if change.get("new_value") is not None else "[dim]-[/dim]"

            table.add_row(
                change.get("key", ""),
                old_val,
                new_val,
                f"[{style}]{change_type}[/{style}]",
            )

        console.print(table)
    else:
        # Summary across all config types
        summaries = result.get("config_types", [])
        if not summaries:
            console.print(f"[green]No drift detected for {name}[/green]")
            return

        table = Table(title=f"Drift Summary: {name}")
        table.add_column("Config Type", style="cyan")
        table.add_column("Drift", style="white")
        table.add_column("Changes", style="white")
        table.add_column("Last Capture", style="dim")

        for s in summaries:
            has_drift = s.get("has_drift", False)
            drift_style = "red" if has_drift else "green"
            drift_text = "Yes" if has_drift else "No"
            table.add_row(
                s.get("config_type", ""),
                f"[{drift_style}]{drift_text}[/{drift_style}]",
                str(s.get("change_count", 0)),
                str(s.get("last_capture", "")),
            )

        console.print(table)
