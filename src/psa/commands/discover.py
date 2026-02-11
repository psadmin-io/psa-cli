"""Domain discovery command."""

import json
import socket
import urllib.error
import urllib.request
from typing import Optional

import typer
from rich.console import Console

from psa.core.config import get_config
from psa.core.domain import DomainDiscovery
from psa.core.domain_cache import update_cache_from_ingest
from psa.core.output import print_domains_table, print_error, print_json, print_success

console = Console()


def _report_to_api(
    ops_url: str,
    hostname: str,
    domains: list,
    environment_id: Optional[str] = None,
) -> dict:
    """Report discovery results to OPS API."""
    url = f"{ops_url.rstrip('/')}/api/v1/scan/ingest"
    if environment_id:
        url += f"?environment_id={environment_id}"

    payload = {
        "hostname": hostname,
        "domains": domains,
        "scan_source": "psa-discover",
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        try:
            error_data = json.loads(error_body)
            raise RuntimeError(error_data.get("detail", str(e)))
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code}: {error_body or str(e)}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed: {e.reason}")


def discover(
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
    domain_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by domain type (app, prcs, pia)",
    ),
    ps_cfg_home: Optional[str] = typer.Option(
        None,
        "--ps-cfg-home",
        envvar="PS_CFG_HOME",
        help="Path to PS_CFG_HOME",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show verbose output including config details",
    ),
    report: bool = typer.Option(
        False,
        "--report",
        "-r",
        help="Report results to OPS API (uses saved config from psa init)",
    ),
    ops_url: Optional[str] = typer.Option(
        None,
        "--ops-url",
        envvar="PSA_OPS_URL",
        help="Report results to OPS API (e.g., http://ops:8002)",
    ),
    environment_id: Optional[str] = typer.Option(
        None,
        "--environment-id",
        "-e",
        envvar="PSA_ENVIRONMENT_ID",
        help="Override environment for discovered domains (defaults to node's default environment)",
    ),
) -> None:
    """
    Discover PeopleSoft domains on this server.

    Scans PS_CFG_HOME for application server, process scheduler,
    and PIA domains. Extracts configuration information from
    domain config files.

    Examples:
        psa discover
        psa discover --json
        psa discover --type app
        psa discover --ps-cfg-home /u01/app/psoft/cfg
        psa discover --report
        psa discover --ops-url http://ops:8002
    """
    # Build config
    config = get_config()
    if ps_cfg_home:
        from pathlib import Path

        config.ps_cfg_home = Path(ps_cfg_home)

    # Discover domains
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
                print_error("Valid types: app, prcs, pia")
                raise typer.Exit(1)
        else:
            domains = discovery.discover_all()

    except PermissionError as e:
        print_error(f"Permission denied accessing domain paths: {e}")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Error during discovery: {e}")
        raise typer.Exit(1)

    # Convert to dicts for output
    domain_dicts = [d.to_dict() for d in domains]

    # Determine OPS URL (--report uses saved config)
    effective_ops_url = ops_url
    effective_env_id = environment_id

    if report and not ops_url:
        if config.ops.is_configured():
            effective_ops_url = config.ops.url
            if not effective_env_id:
                effective_env_id = config.ops.environment_id
        else:
            print_error("OPS not configured. Run 'psa init' first or use --ops-url")
            raise typer.Exit(1)

    # Report to OPS API if URL provided
    if effective_ops_url:
        hostname = socket.gethostname()
        try:
            result = _report_to_api(
                effective_ops_url, hostname, domain_dicts, effective_env_id
            )

            if result.get("errors"):
                for error in result["errors"]:
                    print_error(error)
                raise typer.Exit(1)

            created = result.get("domains_created", 0)
            updated = result.get("domains_updated", 0)
            unchanged = result.get("domains_unchanged", 0)
            print_success(
                f"Reported to OPS: {created} created, {updated} updated, {unchanged} unchanged"
            )

            # Cache domain UUIDs from ingest response (if API returns them)
            if result.get("domains"):
                update_cache_from_ingest(result)

            if json_output:
                print_json(result)
            return

        except RuntimeError as e:
            print_error(f"OPS report failed: {e}")
            raise typer.Exit(1)

    # Remove config from output unless verbose
    if not verbose:
        for d in domain_dicts:
            if not json_output:
                d.pop("config", None)

    # Output results
    if json_output:
        print_json(domain_dicts)
    else:
        if not domains:
            console.print("[dim]No domains found[/dim]")
            console.print(f"[dim]Searched: {config.get_ps_cfg_home()}[/dim]")
        else:
            print_domains_table(domain_dicts)

            if verbose:
                console.print()
                for domain in domains:
                    if domain.config:
                        console.print(f"[cyan]{domain.name}[/cyan] config:")
                        for key, value in domain.config.items():
                            console.print(f"  {key}: {value}")
                        console.print()
