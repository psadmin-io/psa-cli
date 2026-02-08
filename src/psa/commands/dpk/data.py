"""DPK configuration data operations."""

import typer
from pathlib import Path
from typing import Optional
from psa.core.config import get_config
from psa.core.hub import HubClient
from psa.core.output import print_error, print_success, print_info, print_warning

app = typer.Typer(
    name="data",
    help="Manage DPK configuration data (Hiera YAML)",
    no_args_is_help=True,
)


@app.command("sync")
def sync(
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Tier name (DEV, TEST, PROD)"),
    environments: Optional[str] = typer.Option(None, "--environments", "-e", help="Comma-separated environment names"),
    hiera_path: Path = typer.Option(
        Path("/u01/app/psoft/dpk/puppet/production/data/cust"),
        "--hiera-path",
        "-p",
        help="Hiera cust/ directory path"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would sync without writing"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress config default warnings"),
):
    """
    Sync Hiera YAMLs from hub to local Hiera paths.

    Pulls tier and environment YAMLs from hub and writes to:
    - {hiera_path}/tier/{tier}.yaml
    - {hiera_path}/env/{environment}.yaml

    Examples:
        psa dpk data sync --tier DEV --environments HRDEV,FSCMDEV
        psa dpk data sync --tier PROD --environments HRPRD --dry-run
        psa dpk data sync --tier DEV --environments HRDEV --hiera-path /tmp/hiera/cust
    """

    # Get config and connect to hub
    config = get_config()
    if not config.hub.is_configured():
        print_error("Hub not configured. Run 'psa init' first")
        raise typer.Exit(1)

    hub = config.hub

    # Apply config defaults for unspecified options
    defaulted = []
    if not tier and hub.tier:
        tier = hub.tier
        defaulted.append(f"tier={tier}")
    if not environments and hub.environment_name:
        environments = hub.environment_name
        defaulted.append(f"environments={environments}")

    # Show warning for defaulted values
    if defaulted and not quiet and not hub.suppress_fact_warnings:
        print_warning(f"Using config defaults: {', '.join(defaulted)}")

    if not tier and not environments:
        print_error("Specify --tier and/or --environments (or run 'psa init' to set defaults)")
        raise typer.Exit(1)

    client = HubClient(config.hub.url)
    try:
        client.health()
    except Exception:
        print_error("Hub not available")
        raise typer.Exit(1)

    # Call sync API
    params = {}
    if tier:
        params['tier'] = tier
    if environments:
        params['environments'] = environments

    try:
        response = client.sync_yaml(**params)
    except Exception as e:
        print_error(f"Sync failed: {e}")
        raise typer.Exit(1)

    if not response:
        print_warning("No YAML files generated - check tier/environment names")
        raise typer.Exit(1)

    # Write YAMLs to disk
    for rel_path, yaml_content in response.items():
        full_path = hiera_path / rel_path

        if dry_run:
            print_info(f"Would write: {full_path} ({len(yaml_content)} bytes)")
            continue

        # Create directory if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write YAML
        try:
            full_path.write_text(yaml_content)
            print_success(f"Synced: {full_path}")
        except PermissionError:
            print_error(f"Permission denied: {full_path}")
            print_info("Try running with sudo or as the correct user")
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Failed to write {full_path}: {e}")
            raise typer.Exit(1)

    if dry_run:
        print_info("Dry run - no files written")
    else:
        print_success(f"Synced {len(response)} YAML file(s)")


@app.command("get")
def get(
    level: str = typer.Argument(..., help="Level: tier or environment"),
    key: str = typer.Argument(..., help="Tier name or environment name"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file (or stdout)"),
):
    """
    Get single YAML from hub.

    Examples:
        psa dpk data get tier DEV
        psa dpk data get environment HRPRD --output HRPRD.yaml
    """

    if level not in ['tier', 'environment']:
        print_error(f"Invalid level: {level} (must be 'tier' or 'environment')")
        raise typer.Exit(1)

    # Get config and connect to hub
    config = get_config()
    if not config.hub.is_configured():
        print_error("Hub not configured. Run 'psa init' first")
        raise typer.Exit(1)

    client = HubClient(config.hub.url)

    try:
        if level == 'tier':
            yaml_content = client.get_tier_yaml(key)
        else:
            yaml_content = client.get_environment_yaml(key)
    except Exception as e:
        print_error(f"Get failed: {e}")
        raise typer.Exit(1)

    if output:
        try:
            output.write_text(yaml_content)
            print_success(f"Written: {output}")
        except Exception as e:
            print_error(f"Failed to write {output}: {e}")
            raise typer.Exit(1)
    else:
        print(yaml_content)


@app.command("import")
def import_data(
    level: str = typer.Argument(..., help="Level: tier or environment"),
    key: str = typer.Argument(..., help="Tier name or environment name"),
    file: Path = typer.Option(..., "--file", "-f", help="YAML file to import"),
    no_replace: bool = typer.Option(False, "--no-replace", help="Don't delete existing values (merge mode)"),
):
    """
    Import YAML file into hub.

    Parses YAML and upserts config values to hub database.
    By default, replaces all existing config for the level+key.

    Examples:
        psa dpk data import tier DEV --file DEV.yaml
        psa dpk data import environment HRPRD --file HRPRD.yaml
        psa dpk data import tier PROD --file PROD.yaml --no-replace  # Merge mode
    """
    if level not in ['tier', 'environment']:
        print_error(f"Invalid level: {level} (must be 'tier' or 'environment')")
        raise typer.Exit(1)

    if not file.exists():
        print_error(f"File not found: {file}")
        raise typer.Exit(1)

    # Get config and connect to hub
    config = get_config()
    if not config.hub.is_configured():
        print_error("Hub not configured. Run 'psa init' first")
        raise typer.Exit(1)

    client = HubClient(config.hub.url)

    # Read YAML file
    try:
        yaml_content = file.read_text()
    except Exception as e:
        print_error(f"Failed to read {file}: {e}")
        raise typer.Exit(1)

    # Import via API
    print_info(f"Importing {file} as {level}/{key}...")
    try:
        result = client.import_yaml(
            level=level,
            level_key=key,
            yaml_content=yaml_content,
            replace_all=not no_replace
        )
    except Exception as e:
        print_error(f"Import failed: {e}")
        raise typer.Exit(1)

    # Show results
    counts = result.get("import_counts", {})
    created = counts.get("created", 0)
    updated = counts.get("updated", 0)
    deleted = counts.get("deleted", 0)

    mode = "merged" if no_replace else "replaced"
    print_success(f"Imported {level}/{key}: {created} created, {updated} updated, {deleted} deleted ({mode})")


# REMOVED: generate-from-environment command
# Deferred to future iteration - see issue #56

# REMOVED: generate-from-environments command (bulk generation)
# Deferred to issue #49 for future implementation
