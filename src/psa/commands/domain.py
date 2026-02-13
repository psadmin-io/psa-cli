"""Domain management commands."""

import json
import urllib.error
import urllib.request
from typing import List, Optional, Set

import typer
from rich.table import Table

from psa.core.config import get_config
from psa.core.discovery import run_discovery
from psa.core.domain import DomainDiscovery, DomainInfo
from psa.core.domain_cache import get_cached_domain_id
from psa.core.api import ApiClient, ApiError
from psa.core.output import (
    Verbosity,
    console,
    get_verbosity,
    print_domains_table,
    print_error,
    print_info,
    print_json,
    print_success,
    print_warning,
    run_step,
    set_verbosity,
)
from psa.core.psadmin import PsadminExecutor, PsadminResult

app = typer.Typer(
    name="domain",
    help="Manage PeopleSoft domains",
    no_args_is_help=True,
)


def _apply_verbosity(quiet: bool, verbose: bool) -> None:
    """Apply quiet/verbose flags (subcommand-level override)."""
    if quiet is True:
        set_verbosity(Verbosity.QUIET)
    elif verbose is True:
        set_verbosity(Verbosity.VERBOSE)


def _find_domain(name: str, domain_type: Optional[str] = None) -> Optional[DomainInfo]:
    """Find a domain by name."""
    config = get_config()
    discovery = DomainDiscovery(config)
    try:
        return discovery.find_domain(name, domain_type)
    except PermissionError as e:
        print_error(f"Permission denied during discovery: {e}")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Discovery failed: {e}")
        raise typer.Exit(1)


def _resolve_targets(
    name: Optional[str],
    domain_type: Optional[str] = None,
    skip_types: Optional[Set[str]] = None,
) -> List[DomainInfo]:
    """Resolve domain targets: single domain by name, or all via discovery.

    Returns list of DomainInfo. Exits 1 if nothing found.
    """
    if name is not None:
        domain = _find_domain(name, domain_type)
        if not domain:
            print_error(f"Domain '{name}' not found")
            raise typer.Exit(1)
        return [domain]

    # Discover all domains
    config = get_config()
    domains = run_discovery(config, domain_type)
    if skip_types:
        domains = [d for d in domains if d.domain_type not in skip_types]
    if not domains:
        print_error("No domains found")
        raise typer.Exit(1)
    return domains


def _confirm_targets(domains: List[DomainInfo], action: str, all_mode: bool = False) -> bool:
    """Prompt user to confirm action on domains.

    Auto-confirms for single named domain, QUIET mode, or skip_domain_confirm config.
    Always prompts in all-mode (no name specified), even if only 1 domain found.
    """
    if len(domains) == 1 and not all_mode:
        return True
    if get_verbosity() == Verbosity.QUIET:
        return True
    config = get_config()
    if config.skip_domain_confirm:
        return True

    table = Table(title=f"{action.capitalize()} targets")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    for d in domains:
        table.add_row(d.name, d.domain_type)
    console.print(table)
    console.print("[dim]Tip: psa config set skip_domain_confirm true to skip this prompt[/dim]")

    return typer.confirm(f"{action.capitalize()} {len(domains)} domain(s)?")


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
    """Report domain status to PSA-OPS. Never fails the command."""
    status_map = {"running": "Running", "stopped": "Stopped"}
    api_status = status_map.get(status_str, "Unknown")

    config = get_config()
    if not config.ops.is_configured():
        print_warning("PSA-OPS not configured; skipping report")
        return

    domain_id = get_cached_domain_id(name)
    if not domain_id:
        print_warning(f"No cached domain ID for '{name}'; run `psa ops report` first")
        return

    try:
        client = ApiClient(config.ops.url)
        client.update_domain(domain_id, status=api_status)
        console.print("[dim]↑ reported[/dim]")
    except Exception as e:
        print_warning(f"report failed: {e}")


def _parse_status_output(output: str, domain_type: str) -> str:
    """Parse psadmin status output to determine running/stopped status."""
    output_lower = output.lower()

    if domain_type in ("app", "prcs"):
        # Stopped patterns (check first — "is not started" is unambiguous)
        if "not booted" in output_lower or "is not started" in output_lower:
            return "stopped"
        if domain_type == "app" and "no processes" in output_lower:
            return "stopped"
        if domain_type == "prcs" and ("not running" in output_lower or "no process" in output_lower):
            return "stopped"
        # Running patterns
        if "processes running" in output_lower or "server status: active" in output_lower:
            return "running"
        if domain_type == "prcs" and ("process scheduler is running" in output_lower or output_lower.strip() == "started"):
            return "running"
        # tmadmin process table — BBL present means Tuxedo domain is booted
        if "bbl" in output_lower and "prog name" in output_lower:
            return "running"
    elif domain_type == "pia":
        if "running" in output_lower and "not running" not in output_lower:
            return "running"
        if "stopped" in output_lower or "not running" in output_lower:
            return "stopped"

    return "unknown"


def _is_already_stopped(result: PsadminResult, domain: DomainInfo) -> bool:
    """Check if a failed stop/kill result means the domain was already stopped."""
    if result.success:
        return False
    if not result.output.strip():
        return True
    return _parse_status_output(result.output, domain.domain_type) == "stopped"


def _is_already_purged(result: PsadminResult) -> bool:
    """Check if a failed purge means the cache was already empty."""
    if result.success:
        return False
    return "no cache to be purged" in result.output.lower()


def _format_command_error(action: str, name: str, result: PsadminResult) -> str:
    """Format error with fallback for empty psadmin output."""
    if result.output.strip():
        return f"Failed to {action} domain: {result.output}"
    state = "stopped" if action in ("stop", "kill") else "running"
    return f"Failed to {action} domain '{name}' (exit code {result.exit_code}). Domain may already be {state}."


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


@app.command("bounce")
def bounce(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
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
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Full domain bounce

    Examples:
        psa domain bounce APPDOM
        psa domain bounce              # bounce all domains
        psa domain bounce --type app   # bounce all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "bounce", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    failed = 0
    for domain in domains:
        print_info(f"Bouncing {domain.domain_type} domain: {domain.name}")

        stop_result = run_step(
            "Stopping",
            lambda d=domain: _execute_domain_command(d, "stop", executor),
            warn_if=lambda r, d=domain: _is_already_stopped(r, d),
        )
        if not stop_result.success and not _is_already_stopped(stop_result, domain):
            print_warning(f"Stop returned non-zero: {stop_result.output}")
        run_step(
            "Purging cache",
            lambda d=domain: _execute_domain_command(d, "purge", executor),
            warn_if=lambda r: _is_already_purged(r),
        )

        if domain.domain_type != "pia":
            run_step("Flushing IPC", lambda d=domain: _execute_domain_command(d, "flush", executor))
            run_step("Configuring", lambda d=domain: _execute_domain_command(d, "configure", executor))

        result = run_step("Starting", lambda d=domain: _execute_domain_command(d, "start", executor))

        if result.success:
            print_success(f"Domain {domain.name} bounced")
        else:
            print_error(_format_command_error("start", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


@app.command("configure")
def configure(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
    restart: bool = typer.Option(False, "--restart", "-r", help="Start domain after configure"),
    serial: bool = typer.Option(False, "--serial", "-s", help="Start processes serially"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs)",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Stop and configure a domain

    Examples:
        psa domain configure APPDOM
        psa domain configure APPDOM --restart   # stop, configure, start
        psa domain configure              # configure all (skips PIA)
        psa domain configure --type app   # configure all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type, skip_types={"pia"} if name is None else None)
    if name is not None and domains[0].domain_type == "pia":
        print_error("Configure not supported for PIA domains")
        raise typer.Exit(1)
    if not _confirm_targets(domains, "configure", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    failed = 0
    for domain in domains:
        print_info(f"Configuring {domain.domain_type} domain: {domain.name}")

        stop_result = run_step(
            "Stopping",
            lambda d=domain: _execute_domain_command(d, "stop", executor),
            warn_if=lambda r, d=domain: _is_already_stopped(r, d),
        )
        if not stop_result.success and not _is_already_stopped(stop_result, domain):
            print_warning(f"Stop returned non-zero: {stop_result.output}")

        result = run_step("Configuring", lambda d=domain: _execute_domain_command(d, "configure", executor))
        if not result.success:
            print_error(_format_command_error("configure", domain.name, result))
            failed += 1
            continue

        if restart:
            result = run_step("Starting", lambda d=domain: _execute_domain_command(d, "start", executor))
            if result.success:
                print_success(f"Domain {domain.name} configured and started")
            else:
                print_error(_format_command_error("start", domain.name, result))
                failed += 1
        else:
            print_success(f"Domain {domain.name} configured")

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


def _resolve_api_domain_id(client: ApiClient, name: str) -> str:
    """Resolve domain name to UUID via cache then PSA-OPS API."""
    cached = get_cached_domain_id(name)
    if cached:
        return cached
    domain = client.resolve_domain(name)
    if not domain:
        print_error(f"Domain '{name}' not found in PSA-OPS")
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
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Show config drift for a domain

    Without --type: shows drift summary across all config types.
    With --type: shows detailed key-level changes for that config type.

    Examples:
        psa domain drift APPDOM
        psa domain drift APPDOM --type psappsrv.cfg
    """
    _apply_verbosity(quiet, verbose)
    config = get_config()
    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa config setup' first")
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


@app.command("flush")
def flush(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs)",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Clear domain IPC resources

    Examples:
        psa domain flush APPDOM
        psa domain flush              # flush all (skips PIA)
        psa domain flush --type app   # flush all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type, skip_types={"pia"} if name is None else None)
    if name is not None and domains[0].domain_type == "pia":
        print_warning("Flush not applicable for PIA domains")
        return
    if not _confirm_targets(domains, "flush", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    failed = 0
    for domain in domains:
        print_info(f"Flushing IPC for {domain.domain_type} domain: {domain.name}")
        result = run_step("Flushing IPC", lambda d=domain: _execute_domain_command(d, "flush", executor))

        if result.success:
            print_success(f"Domain {domain.name} IPC flushed")
        else:
            print_error(_format_command_error("flush", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


@app.command("kill")
def kill(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Force stop a domain

    Examples:
        psa domain kill APPDOM
        psa domain kill              # kill all domains
        psa domain kill --type app   # kill all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "kill", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    failed = 0
    for domain in domains:
        print_info(f"Force stopping {domain.domain_type} domain: {domain.name}")
        result = run_step(
            "Killing",
            lambda d=domain: _execute_domain_command(d, "kill", executor),
            warn_if=lambda r, d=domain: _is_already_stopped(r, d),
        )

        if result.success:
            print_success(f"Domain {domain.name} killed")
        elif _is_already_stopped(result, domain):
            print_warning(f"Domain {domain.name} already stopped")
        else:
            print_error(_format_command_error("kill", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


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
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """List all domains"""
    _apply_verbosity(quiet, verbose)
    config = get_config()
    domains = run_discovery(config, domain_type)
    domain_dicts = [d.to_dict() for d in domains]

    if json_output:
        print_json(domain_dicts)
        return

    if not domains:
        console.print("[dim]No domains found[/dim]")
        console.print(f"[dim]Searched: {config.get_ps_cfg_home()}[/dim]")
        return

    if get_verbosity() >= Verbosity.VERBOSE:
        table = Table(title="PeopleSoft Domains")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("DB", style="white")
        table.add_column("Port", style="white")
        table.add_column("App Server", style="white")
        table.add_column("Profile", style="white")
        table.add_column("Path", style="dim")
        for d in domain_dicts:
            cfg = d.get("config", {})
            status = d.get("status", "unknown")
            status_style = "green" if status == "running" else "red"
            table.add_row(
                d.get("name", "unknown"),
                d.get("type", "unknown"),
                f"[{status_style}]{status}[/{status_style}]",
                cfg.get("db_name", ""),
                cfg.get("jolt_port", ""),
                cfg.get("app_server", ""),
                cfg.get("web_profile", ""),
                str(d.get("path", "")),
            )
        console.print(table)
    else:
        # Strip config from default table output
        for d in domain_dicts:
            d.pop("config", None)
        print_domains_table(domain_dicts)


@app.command("purge")
def purge(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, pia)",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Clear domain cache

    Examples:
        psa domain purge APPDOM
        psa domain purge              # purge all domains
        psa domain purge --type app   # purge all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "purge", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    failed = 0
    for domain in domains:
        print_info(f"Purging cache for {domain.domain_type} domain: {domain.name}")
        result = run_step(
            "Purging cache",
            lambda d=domain: _execute_domain_command(d, "purge", executor),
            warn_if=lambda r: _is_already_purged(r),
        )

        if result.success:
            print_success(f"Domain {domain.name} cache purged")
        elif _is_already_purged(result):
            print_warning(f"Domain {domain.name} cache already empty")
        else:
            print_error(_format_command_error("purge", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


@app.command("restart")
def restart(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
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
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Restart a domain

    Examples:
        psa domain restart APPDOM
        psa domain restart              # restart all domains
        psa domain restart --type app   # restart all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "restart", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    failed = 0
    for domain in domains:
        print_info(f"Restarting {domain.domain_type} domain: {domain.name}")

        stop_result = run_step(
            "Stopping",
            lambda d=domain: _execute_domain_command(d, "stop", executor),
            warn_if=lambda r, d=domain: _is_already_stopped(r, d),
        )
        if not stop_result.success and not _is_already_stopped(stop_result, domain):
            print_warning(f"Stop returned non-zero: {stop_result.output}")

        result = run_step("Starting", lambda d=domain: _execute_domain_command(d, "start", executor))
        if result.success:
            print_success(f"Domain {domain.name} restarted")
        else:
            print_error(_format_command_error("start", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


@app.command("set-env")
def set_env(
    domain_id: str = typer.Argument(..., help="Domain ID (from PSA-OPS)"),
    environment_id: str = typer.Argument(..., help="Environment ID to assign"),
    ops_url: Optional[str] = typer.Option(
        None,
        "--ops-url",
        envvar="PSA_OPS_URL",
        help="PSA-OPS URL (or uses saved config from psa config setup)",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Assign an environment to a domain in PSA-OPS

    Examples:
        psa domain set-env abc123 def456
        psa domain set-env abc123 def456 --ops-url http://ops:8002
    """
    _apply_verbosity(quiet, verbose)
    config = get_config()

    effective_ops_url = ops_url
    if not effective_ops_url:
        if config.ops.is_configured():
            effective_ops_url = config.ops.url
        else:
            print_error("PSA-OPS not configured. Run 'psa config setup' first or use --ops-url")
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


@app.command("start")
def start(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
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
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Start a domain

    Examples:
        psa domain start APPDOM
        psa domain start PRCSDOM --serial
        psa domain start              # start all domains
        psa domain start --type app   # start all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "start", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    if serial:
        executor.config.parallel_boot = False

    failed = 0
    for domain in domains:
        print_info(f"Starting {domain.domain_type} domain: {domain.name}")
        result = run_step("Starting", lambda d=domain: _execute_domain_command(d, "start", executor))

        if result.success:
            print_success(f"Domain {domain.name} started")
        else:
            print_error(_format_command_error("start", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)


@app.command("status")
def status(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
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
        help="Report status to PSA-OPS",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Show status of a domain

    Examples:
        psa domain status APPDOM           # Short output (running/stopped)
        psa domain status APPDOM --full    # Full psadmin output
        psa domain status APPDOM --json    # Structured JSON
        psa domain status APPDOM --report  # Report status to PSA-OPS
        psa domain status                  # Status of all domains
        psa domain status --type app       # Status of all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    # No confirmation for read-only status

    executor = _get_executor()

    # Multi-domain: table or JSON array
    if len(domains) > 1:
        results = []
        for domain in domains:
            result = _execute_domain_command(domain, "status", executor)
            status_str = _parse_status_output(result.output, domain.domain_type)
            results.append((domain, result, status_str))

        if json_output:
            json_list = [_format_status_json(d, r) for d, r, _ in results]
            console.print_json(json.dumps(json_list))
        elif full or get_verbosity() == Verbosity.VERBOSE:
            for domain, result, _ in results:
                console.print(f"\n[bold]{domain.name}[/bold] ({domain.domain_type})")
                console.print(result.output)
        else:
            table = Table(title="Domain Status")
            table.add_column("Name", style="cyan")
            table.add_column("Type", style="magenta")
            table.add_column("Status")
            for domain, _, status_str in results:
                if status_str == "running":
                    style = "bold green"
                elif status_str == "stopped":
                    style = "bold yellow"
                else:
                    style = "dim"
                table.add_row(domain.name, domain.domain_type, f"[{style}]{status_str}[/{style}]")
            console.print(table)

        if report:
            for domain, _, status_str in results:
                _report_status_to_api(domain.name, status_str)
        return

    # Single domain: original behavior
    domain = domains[0]
    result = _execute_domain_command(domain, "status", executor)
    status_str = _parse_status_output(result.output, domain.domain_type)

    if json_output:
        console.print_json(json.dumps(_format_status_json(domain, result)))
    elif full or get_verbosity() == Verbosity.VERBOSE:
        console.print(result.output)
    else:
        if status_str == "running":
            console.print(f"[green]{domain.name}[/green]: [bold green]running[/bold green]")
        elif status_str == "stopped":
            console.print(f"[yellow]{domain.name}[/yellow]: [bold yellow]stopped[/bold yellow]")
        else:
            console.print(f"[dim]{domain.name}[/dim]: [dim]unknown[/dim]")

    if report:
        _report_status_to_api(domain.name, status_str)


@app.command("stop")
def stop(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
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
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Stop a domain

    Examples:
        psa domain stop APPDOM
        psa domain stop PRCSDOM --force
        psa domain stop              # stop all domains
        psa domain stop --type app   # stop all app domains
    """
    _apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "stop", all_mode=name is None):
        raise typer.Abort()

    executor = _get_executor()
    action = "kill" if force else "stop"

    failed = 0
    for domain in domains:
        print_info(f"Stopping {domain.domain_type} domain: {domain.name}")
        result = run_step(
            "Stopping",
            lambda d=domain: _execute_domain_command(d, action, executor),
            warn_if=lambda r, d=domain: _is_already_stopped(r, d),
        )

        if result.success:
            print_success(f"Domain {domain.name} stopped")
        elif _is_already_stopped(result, domain):
            print_warning(f"Domain {domain.name} already stopped")
        else:
            print_error(_format_command_error(action, domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)
