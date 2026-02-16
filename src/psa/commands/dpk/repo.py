"""DPK repository management commands."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.core.config import PsaConfig
from psa.core.dpk_repo import DpkRepo
from psa.core.output import print_error, print_info, print_success, print_warning

console = Console()

DEFAULT_REPO_PATH = "/cm_psft_dpks/dpk/linux/tools"

app = typer.Typer(
    name="repo",
    help="Manage DPK file repository",
    no_args_is_help=True,
)


@app.command("init")
def init(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help=f"Repository path (default: {DEFAULT_REPO_PATH})",
    ),
) -> None:
    """
    Initialize DPK repository configuration

    Validates the directory exists and saves the path to config.

    Examples:
        psa dpk repo init
        psa dpk repo init --path /nfs/dpk/linux/tools
    """
    repo_path = path or Path(DEFAULT_REPO_PATH)

    if not repo_path.exists():
        print_error(f"Directory not found: {repo_path}")
        raise typer.Exit(1)

    if not repo_path.is_dir():
        print_error(f"Not a directory: {repo_path}")
        raise typer.Exit(1)

    config = PsaConfig.load()
    config.dpk_repo_path = str(repo_path)
    config.save()

    print_success(f"DPK repo path set: {repo_path}")

    # Show version summary
    repo = DpkRepo(repo_path)
    versions = repo.list_versions()
    if versions:
        print_info(f"Found {len(versions)} version(s)")
    else:
        print_warning("No DPK versions found in repository")


@app.command("status")
def status() -> None:
    """
    Show DPK repository status

    Displays configured path, accessibility, and version count.

    Examples:
        psa dpk repo status
    """
    config = PsaConfig.load()

    if not config.dpk_repo_path:
        print_warning("DPK repo not configured")
        print_info("Run: psa dpk repo init --path <path>")
        raise typer.Exit(1)

    repo_path = Path(config.dpk_repo_path)
    console.print(f"[bold]DPK Repository[/bold]\n")
    console.print(f"  Path: [cyan]{repo_path}[/cyan]")

    if not repo_path.exists():
        console.print(f"  Status: [red]not found[/red]")
        raise typer.Exit(1)

    if not repo_path.is_dir():
        console.print(f"  Status: [red]not a directory[/red]")
        raise typer.Exit(1)

    console.print(f"  Status: [green]accessible[/green]")

    repo = DpkRepo(repo_path)
    versions = repo.list_versions()
    console.print(f"  Versions: {len(versions)}")

    if versions:
        latest = versions[0]
        console.print(f"  Latest: [cyan]{latest.label}[/cyan] ({latest.zip_count} zips, {latest.human_size})")


@app.command("list")
def list_versions(
    version: Optional[str] = typer.Option(
        None,
        "--version",
        "-v",
        help="Filter by major version (e.g. 862)",
    ),
) -> None:
    """
    List available DPK versions in repository

    Scans the repository for version directories and shows zip count and size.

    Examples:
        psa dpk repo list
        psa dpk repo list --version 862
    """
    config = PsaConfig.load()

    if not config.dpk_repo_path:
        print_error("DPK repo not configured. Run: psa dpk repo init --path <path>")
        raise typer.Exit(1)

    repo_path = Path(config.dpk_repo_path)
    if not repo_path.is_dir():
        print_error(f"Repo path not accessible: {repo_path}")
        raise typer.Exit(1)

    repo = DpkRepo(repo_path)
    versions = repo.list_versions(filter_major=version)

    if not versions:
        if version:
            print_warning(f"No versions found for major version {version}")
        else:
            print_warning("No DPK versions found in repository")
        return

    table = Table(title="DPK Versions")
    table.add_column("Version", style="cyan")
    table.add_column("Zips", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Path", style="dim")

    for v in versions:
        table.add_row(v.label, str(v.zip_count), v.human_size, str(v.path))

    console.print(table)
    console.print(f"\n{len(versions)} version(s) found")
