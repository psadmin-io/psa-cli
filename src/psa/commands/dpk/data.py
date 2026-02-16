"""DPK configuration data operations."""

import typer
from pathlib import Path
from typing import Optional
from psa.core.config import get_config
from psa.core.api import ApiClient
from psa.core.output import print_error, print_success, print_info, print_warning

app = typer.Typer(
    name="data",
    help="Manage DPK configuration data (Hiera YAML)",
    no_args_is_help=True,
)


@app.command("get")
def get(
    level: str = typer.Argument(..., help="Level: tier or environment"),
    key: str = typer.Argument(..., help="Tier name or environment name"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file (or stdout)"),
):
    """
    Get single YAML from PSA-OPS

    Examples:
        psa dpk data get tier DEV
        psa dpk data get environment HRPRD --output HRPRD.yaml
    """

    if level not in ['tier', 'environment']:
        print_error(f"Invalid level: {level} (must be 'tier' or 'environment')")
        raise typer.Exit(1)

    # Get config and connect to PSA-OPS
    config = get_config()
    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

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
    Import YAML file into PSA-OPS

    Parses YAML and upserts config values to PSA-OPS database.
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

    # Get config and connect to PSA-OPS
    config = get_config()
    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)

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


def _sync_ops_data(
    tier: Optional[str] = None,
    environments: Optional[str] = None,
    hiera_path: Optional[Path] = None,
    dry_run: bool = False,
) -> None:
    """Sync Hiera YAMLs from PSA-OPS to local Hiera paths.

    Core logic extracted for use by both 'psa dpk data sync' (removed) and
    'psa dpk sync --data'.  Raises typer.Exit on failure.
    """
    if hiera_path is None:
        hiera_path = Path("/u01/app/psoft/dpk/puppet/production/data/cust")

    # Get config and connect to PSA-OPS
    config = get_config()
    if not config.ops.is_configured():
        print_error("PSA-OPS not configured. Run 'psa ops setup --url <url>' first")
        raise typer.Exit(1)

    ops = config.ops

    # Apply config defaults for unspecified options
    defaulted = []
    if not tier and ops.tier:
        tier = ops.tier
        defaulted.append(f"tier={tier}")
    if not environments and ops.environment_name:
        environments = ops.environment_name
        defaulted.append(f"environments={environments}")

    # Show warning for defaulted values (print_warning is verbosity-aware)
    if defaulted and not ops.suppress_fact_warnings:
        print_warning(f"Using config defaults: {', '.join(defaulted)}")

    if not tier and not environments:
        print_error("Specify --tier and/or --environments (or run 'psa ops setup' to set defaults)")
        raise typer.Exit(1)

    client = ApiClient(config.ops.url)
    try:
        client.health()
    except Exception:
        print_error("PSA-OPS not available")
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


# REMOVED: generate-from-environment command
# Deferred to future iteration - see issue #56

# REMOVED: generate-from-environments command (bulk generation)
# Deferred to issue #49 for future implementation
