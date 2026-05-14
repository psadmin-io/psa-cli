"""Domain management commands."""

import json
from pathlib import Path
from typing import List, Optional, Set

import typer
from rich.table import Table

from psa.core.api import ApiClient, ApiError, get_hostname
from psa.core.compare import (
    CompareResult,
    diff_configs,
    extract_api_properties,
    format_age,
    get_primary_config,
    list_archive_backups,
    parse_config_to_flat,
    resolve_web_config_path,
)
from psa.core.config import PsaConfig, get_config
from psa.core.discovery import run_discovery
from psa.core.domain import DomainDiscovery, DomainInfo
from psa.core.domain_cache import get_cached_domain_id, update_cache_from_ingest
from psa.core.fileops import SudoFileOps
from psa.core.output import (
    Verbosity,
    apply_verbosity,
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


def _confirm_targets(domains: List[DomainInfo], action: str, all_mode: bool = False, force: bool = False) -> bool:
    """Prompt user to confirm action on domains.

    Auto-confirms for single named domain, QUIET mode, --force flag, or skip_domain_confirm config.
    Always prompts in all-mode (no name specified), even if only 1 domain found.
    """
    if len(domains) == 1 and not all_mode:
        return True
    if get_verbosity() == Verbosity.QUIET:
        return True
    config = get_config()
    if config.skip_domain_confirm or force:
        return True

    table = Table(title=f"{action.capitalize()} targets")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    for d in domains:
        table.add_row(d.name, d.domain_type)
    console.print(table)
    console.print("[dim]Tip: use --force or `psa config set skip_domain_confirm true` to skip this prompt[/dim]")

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
            "delete": executor.app_delete,
        },
        "prcs": {
            "status": executor.prcs_status,
            "start": executor.prcs_start,
            "stop": executor.prcs_stop,
            "kill": executor.prcs_kill,
            "configure": executor.prcs_configure,
            "purge": executor.prcs_purge,
            "flush": executor.prcs_flush,
            "delete": executor.prcs_delete,
        },
        "web": {
            "status": executor.web_status,
            "start": executor.web_start,
            "stop": executor.web_stop,
            "kill": executor.web_kill,
            "purge": executor.web_purge,
            "delete": executor.web_delete,
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
    elif domain_type == "web":
        # Stopped patterns first ("not started" must precede "started" check)
        if "not started" in output_lower or "stopped" in output_lower or "not running" in output_lower:
            return "stopped"
        if "started" in output_lower or "running" in output_lower:
            return "running"

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
        help="Domain type (app, prcs, web)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
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
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "bounce", all_mode=name is None, force=force):
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

        if domain.domain_type != "web":
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
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Stop and configure a domain

    Examples:
        psa domain configure APPDOM
        psa domain configure APPDOM --restart   # stop, configure, start
        psa domain configure              # configure all (skips web)
        psa domain configure --type app   # configure all app domains
    """
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type, skip_types={"web"} if name is None else None)
    if name is not None and domains[0].domain_type == "web":
        print_error("Configure not supported for web domains")
        raise typer.Exit(1)
    if not _confirm_targets(domains, "configure", all_mode=name is None, force=force):
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
        print_info("Run 'psa ops register' to push locally-discovered domains to PSA-OPS")
        raise typer.Exit(1)
    return domain["id"]


def _resolve_config_path(domain: DomainInfo, config_name: str, fileops: SudoFileOps) -> Path:
    """Resolve the live config file path for a domain."""
    if domain.domain_type == "web":
        path = resolve_web_config_path(fileops, domain.path)
        if not path:
            print_error(f"Cannot find configuration.properties for web domain '{domain.name}'")
            raise typer.Exit(1)
        return path
    return domain.path / config_name


def _render_compare_table(
    name: str,
    config_name: str,
    changes: list,
    left_label: str,
    right_label: str,
) -> None:
    """Render compare results as a Rich table."""
    if not changes:
        console.print(f"[green]No differences: {name} — {left_label} vs {right_label}[/green]")
        return

    table = Table(title=f"Compare: {name} ({config_name})")
    table.add_column("Key", style="cyan")
    table.add_column(left_label, style="red")
    table.add_column(right_label, style="green")
    table.add_column("Change", style="dim")

    for c in changes:
        style = "yellow"
        if c.change_type == "added":
            style = "green"
        elif c.change_type == "removed":
            style = "red"
        old_val = c.old_value if c.old_value is not None else "[dim]-[/dim]"
        new_val = c.new_value if c.new_value is not None else "[dim]-[/dim]"
        table.add_row(c.key, old_val, new_val, f"[{style}]{c.change_type}[/{style}]")

    console.print(table)


def _compare_domain_ops(
    domain: DomainInfo,
    config: PsaConfig,
    commit: bool,
    json_output: bool,
    config_type: Optional[str] = None,
) -> bool:
    """Compare a single domain against its Ops baseline and optionally commit.

    Returns True on success, False on failure.
    """
    name = domain.name
    config_name = config_type or get_primary_config(domain.domain_type)

    # Read current local config
    fileops = SudoFileOps(config)
    config_path = _resolve_config_path(domain, config_name, fileops)
    current_content = fileops.read_text(config_path)
    if current_content is None:
        print_error(f"Cannot read {config_path}")
        return False

    current_flat = parse_config_to_flat(current_content, config_name)

    # Fetch Ops baseline
    client = ApiClient(config.ops.url)
    domain_id = _resolve_api_domain_id(client, name)

    # Push current config so API always has live server state
    if domain.config_files:
        try:
            client.push_current_config(domain_id, domain.config_files)
        except Exception as e:
            print_warning(f"Failed to push current config for {name}: {e}")

    try:
        api_config = client.get_latest_config(domain_id, config_name)
    except ApiError as e:
        print_error(f"API error for {name}: {e}")
        return False

    # Determine diff
    if api_config:
        parsed_content = api_config.get("parsed_content")
        if not parsed_content:
            print_error(f"No parsed content in API config for '{name}'")
            return False
        old_flat = extract_api_properties(parsed_content, config_name)
        changes = diff_configs(old_flat, current_flat)
    else:
        # No baseline exists
        old_flat = None
        changes = None

    # -- Commit flow --
    if changes is not None and len(changes) == 0:
        # No drift
        if json_output:
            data = {
                "domain": name,
                "config_type": config_name,
                "has_drift": False,
                "committed": False,
                "changes": [],
            }
            console.print_json(json.dumps(data, default=str))
        else:
            print_info(f"{name}: config matches Ops baseline.")
        return True

    if old_flat is None:
        # No baseline in Ops
        if json_output:
            auto = True
        elif commit:
            auto = True
        else:
            print_info(f"{name}: no baseline in Ops ({config_name}, {len(current_flat)} keys)")
            auto = typer.confirm("Commit current config as baseline?", default=False)

        if not auto:
            return True  # user declined, not a failure
    else:
        # Changes detected -- show diff
        if not json_output:
            _render_compare_table(name, config_name, changes, "OPS Capture", "Current")

        if json_output:
            auto = True
        elif commit:
            auto = True
        else:
            auto = typer.confirm("Commit to Ops?", default=False)

        if not auto:
            if json_output:
                data = {
                    "domain": name,
                    "config_type": config_name,
                    "has_drift": True,
                    "committed": False,
                    "changes": [
                        {
                            "key": c.key,
                            "old_value": c.old_value,
                            "new_value": c.new_value,
                            "change_type": c.change_type,
                        }
                        for c in changes
                    ],
                }
                console.print_json(json.dumps(data, default=str))
            return True

    # Push via ingest
    try:
        hostname = get_hostname()
        domain_dicts = [domain.to_dict()]
        environment_id = config.ops.environment_id
        result = client.ingest_scan(
            hostname=hostname,
            domains=domain_dicts,
            environment_id=environment_id,
        )
        if result.get("domains"):
            update_cache_from_ingest(result)

        if json_output:
            data = {
                "domain": name,
                "config_type": config_name,
                "has_drift": changes is not None and len(changes) > 0,
                "committed": True,
                "changes": [
                    {
                        "key": c.key,
                        "old_value": c.old_value,
                        "new_value": c.new_value,
                        "change_type": c.change_type,
                    }
                    for c in (changes or [])
                ],
            }
            console.print_json(json.dumps(data, default=str))
        else:
            print_success(f"Committed {name} config to Ops")
        return True
    except ApiError as e:
        print_error(f"Commit failed for {name}: {e}")
        return False


@app.command("compare")
def compare(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
    ops: bool = typer.Option(
        False,
        "--ops",
        help="Compare current local config vs last PSA-OPS capture",
    ),
    commit: bool = typer.Option(
        False,
        "--commit",
        help="Push changes to Ops without prompting",
    ),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="Compare current config vs arbitrary file",
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Auto-pick newest archive backup (skip interactive picker)",
    ),
    config_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Config type (default: primary for domain type)",
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
    Compare domain config against a previous version

    Default: interactive archive picker.
    Use --latest to auto-pick newest archive backup.
    Use --ops to compare against last PSA-OPS capture.
    Use --file to compare against an arbitrary file.

    Examples:
        psa domain compare APPDOM
        psa domain compare APPDOM --latest
        psa domain compare APPDOM --ops
        psa domain compare --ops              # all domains vs Ops
        psa domain compare --ops --commit     # commit all without prompting
        psa domain compare APPDOM --file /path/to/old.cfg
        psa domain compare APPDOM --type psappsrv.cfg
        psa domain compare APPDOM --json
    """
    apply_verbosity(quiet, verbose)

    # Validate mutual exclusion of --latest, --ops, --file
    exclusive_count = sum([latest, ops, file is not None])
    if exclusive_count > 1:
        print_error("--latest, --ops, and --file are mutually exclusive")
        raise typer.Exit(1)

    # --ops mode: supports optional name (all domains when omitted)
    if ops:
        config = get_config()
        if not config.ops.is_configured():
            print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
            raise typer.Exit(1)

        domains = _resolve_targets(name)
        for domain in domains:
            ok = _compare_domain_ops(
                domain,
                config,
                commit=commit or json_output,
                json_output=json_output,
                config_type=config_type,
            )
            if not ok:
                raise typer.Exit(1)
        return

    # Non-ops modes require a domain name
    if name is None:
        print_error("Domain name required for archive/file compare. Use --ops for all domains.")
        raise typer.Exit(1)

    # 1. Find domain locally
    domain = _find_domain(name)
    if not domain:
        print_error(f"Domain '{name}' not found")
        raise typer.Exit(1)

    # 2. Determine config type
    config_name = config_type or get_primary_config(domain.domain_type)

    # 3. Read + parse current config
    config = get_config()
    fileops = SudoFileOps(config)
    config_path = _resolve_config_path(domain, config_name, fileops)

    current_content = fileops.read_text(config_path)
    if current_content is None:
        print_error(f"Cannot read {config_path}")
        raise typer.Exit(1)

    current_flat = parse_config_to_flat(current_content, config_name)

    # 4. Get comparison target
    if file:
        # Compare vs arbitrary file
        file_path = Path(file)
        file_content = fileops.read_text(file_path)
        if file_content is None:
            print_error(f"Cannot read {file}")
            raise typer.Exit(1)

        old_flat = parse_config_to_flat(file_content, config_name)
        left_label = str(file_path.name)
        right_label = "Current"

    else:
        # Default: compare vs Archive backup
        if domain.domain_type == "web":
            print_error("Archive comparison not supported for web domains. Use --ops or --file instead")
            raise typer.Exit(1)

        archive_path = domain.path / "Archive"
        backups = list_archive_backups(fileops, archive_path, config_name)
        if not backups:
            print_error(f"No Archive backups found for {config_name} in {archive_path}")
            raise typer.Exit(1)

        # Pick which backup to compare against
        if latest or json_output or quiet:
            selected = backups[0]
        else:
            console.print(f"Archive backups for {config_name}:")
            for i, b in enumerate(backups, 1):
                age = f"  ({format_age(b.parsed_dt)})" if b.parsed_dt else ""
                console.print(f"  {i}. {b.name}{age}")
            choice = typer.prompt("Select", default="1")
            try:
                idx = int(choice) - 1
                if idx < 0 or idx >= len(backups):
                    raise ValueError
            except ValueError:
                print_error(f"Invalid selection: {choice}")
                raise typer.Exit(1)
            selected = backups[idx]

        archive_content = fileops.read_text(selected.path)
        if archive_content is None:
            print_error(f"Cannot read archive file {selected.path}")
            raise typer.Exit(1)

        old_flat = parse_config_to_flat(archive_content, config_name)
        left_label = selected.name
        right_label = "Current"

    # 5. Diff
    changes = diff_configs(old_flat, current_flat)

    # 6. Render
    if json_output:
        data = {
            "domain": name,
            "config_type": config_name,
            "has_drift": len(changes) > 0,
            "left_label": left_label,
            "right_label": right_label,
            "changes": [
                {
                    "key": c.key,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "change_type": c.change_type,
                }
                for c in changes
            ],
        }
        console.print_json(json.dumps(data, default=str))
        return

    _render_compare_table(name, config_name, changes, left_label, right_label)


@app.command("flush")
def flush(
    name: Optional[str] = typer.Argument(None, help="Domain name (omit for all)"),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Clear domain IPC resources

    Examples:
        psa domain flush APPDOM
        psa domain flush              # flush all (skips web)
        psa domain flush --type app   # flush all app domains
    """
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type, skip_types={"web"} if name is None else None)
    if name is not None and domains[0].domain_type == "web":
        print_warning("Flush not applicable for web domains")
        return
    if not _confirm_targets(domains, "flush", all_mode=name is None, force=force):
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
        help="Domain type (app, prcs, web)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
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
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "kill", all_mode=name is None, force=force):
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
        help="Filter by domain type (app, prcs, web)",
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
    apply_verbosity(quiet, verbose)
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
        help="Domain type (app, prcs, web)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
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
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "purge", all_mode=name is None, force=force):
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
        help="Domain type (app, prcs, web)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
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
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "restart", all_mode=name is None, force=force):
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
        help="Domain type (app, prcs, web)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
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
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "start", all_mode=name is None, force=force):
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
        help="Domain type (app, prcs, web) - auto-detected if not specified",
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
    apply_verbosity(quiet, verbose)
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
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Domain type (app, prcs, web)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """
    Stop a domain

    Examples:
        psa domain stop APPDOM
        psa domain stop              # stop all domains
        psa domain stop --type app   # stop all app domains
    """
    apply_verbosity(quiet, verbose)
    domains = _resolve_targets(name, domain_type)
    if not _confirm_targets(domains, "stop", all_mode=name is None, force=force):
        raise typer.Abort()

    executor = _get_executor()

    failed = 0
    for domain in domains:
        print_info(f"Stopping {domain.domain_type} domain: {domain.name}")
        result = run_step(
            "Stopping",
            lambda d=domain: _execute_domain_command(d, "stop", executor),
            warn_if=lambda r, d=domain: _is_already_stopped(r, d),
        )

        if result.success:
            print_success(f"Domain {domain.name} stopped")
        elif _is_already_stopped(result, domain):
            print_warning(f"Domain {domain.name} already stopped")
        else:
            print_error(_format_command_error("stop", domain.name, result))
            failed += 1

    if failed and len(domains) > 1:
        print_warning(f"{len(domains) - failed}/{len(domains)} succeeded, {failed} failed")
    if failed:
        raise typer.Exit(1)
