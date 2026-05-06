"""PSA Kit management commands."""

import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from psa.core.config import (
    DEFAULT_DPK_CUST_HOME,
    DEFAULT_PSA_KIT,
    PsaConfig,
    get_config,
)
from psa.core.output import print_error, print_info, print_success, print_warning

console = Console()

PSA_KIT_REPO_SSH = "git@github.com:psadmin-io/psa-kit.git"
PSA_KIT_REPO_HTTPS = "https://github.com/psadmin-io/psa-kit.git"

app = typer.Typer(
    name="kit",
    help="Manage PSA Kit installation",
    no_args_is_help=True,
)


def _resolve_kit_path(dest: Optional[Path] = None) -> Path:
    """Resolve kit path: --dest -> $PSA_KIT -> config -> DEFAULT_PSA_KIT."""
    if dest:
        return dest.resolve()
    if psa_kit := os.environ.get("PSA_KIT"):
        return Path(psa_kit)
    config = get_config()
    if config.psa_kit_path:
        return config.psa_kit_path
    return Path(DEFAULT_PSA_KIT)


def _resolve_dpk_cust_home(cust: Optional[Path] = None) -> Path:
    """Resolve DPK_CUST_HOME: --cust -> $DPK_CUST_HOME -> config -> DEFAULT_DPK_CUST_HOME."""
    if cust:
        return cust.resolve()
    if dpk_cust := os.environ.get("DPK_CUST_HOME"):
        return Path(dpk_cust)
    config = get_config()
    if config.dpk_cust_home:
        return config.dpk_cust_home
    return Path(DEFAULT_DPK_CUST_HOME)


def _scaffold_dpk_cust_home(cust_path: Path) -> None:
    """Scaffold DPK_CUST_HOME (flat layout). Delegates to shared helper."""
    from psa.commands.dpk.init import scaffold_dpk_cust_home
    scaffold_dpk_cust_home(cust_path)


@app.command("install")
def kit_install(
    source: str = typer.Option(
        "git",
        "--source",
        "-s",
        help="Install source: git or file",
    ),
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to zip file (for --source file)",
    ),
    dest: Optional[Path] = typer.Option(
        None,
        "--dest",
        "-d",
        help=f"Kit install location (or $PSA_KIT, default: {DEFAULT_PSA_KIT})",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        "-b",
        help="Git branch or tag (default: latest tag)",
    ),
    cust: Optional[Path] = typer.Option(
        None,
        "--cust",
        help=f"DPK_CUST_HOME location (or $DPK_CUST_HOME, default: {DEFAULT_DPK_CUST_HOME})",
    ),
) -> None:
    """
    Install PSA Kit and scaffold DPK_CUST_HOME directory.

    Clones the psa-kit repo (or extracts a zip) and creates the customer
    customization directory structure.

    Examples:
        psa kit install
        psa kit install --branch v1.0.0
        psa kit install --source file --path /tmp/psa-kit.zip
        psa kit install --dest /opt/psa-kit --cust /opt/dpk-cust
    """
    resolved_dest = _resolve_kit_path(dest)
    resolved_cust = _resolve_dpk_cust_home(cust)

    # Check if dest is non-empty
    if resolved_dest.exists() and any(resolved_dest.iterdir()):
        print_error(f"Destination not empty: {resolved_dest}")
        print_info("Remove existing files or choose a different --dest")
        raise typer.Exit(1)

    print_info(f"Kit destination: {resolved_dest}")
    print_info(f"DPK_CUST_HOME location: {resolved_cust}")

    if source == "git":
        # Try SSH first (private repo), fall back to HTTPS
        for repo_url in [PSA_KIT_REPO_SSH, PSA_KIT_REPO_HTTPS]:
            clone_args = ["git", "clone", "--depth", "1"]
            if branch:
                clone_args.extend(["--branch", branch])
            clone_args.extend([repo_url, str(resolved_dest)])

            print_info(f"Cloning from {repo_url}...")
            try:
                result = subprocess.run(
                    clone_args,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    print_success(f"Kit installed to {resolved_dest}")
                    break
                # Clean up failed clone attempt before retry
                if resolved_dest.exists():
                    import shutil
                    shutil.rmtree(resolved_dest)
                if repo_url == PSA_KIT_REPO_HTTPS:
                    print_error(f"Git clone failed: {result.stderr.strip()}")
                    raise typer.Exit(1)
                print_info("SSH clone failed, trying HTTPS...")
            except FileNotFoundError:
                print_error("git not found. Install git first")
                raise typer.Exit(1)
            except subprocess.TimeoutExpired:
                print_error("Git clone timed out")
                raise typer.Exit(1)

    elif source == "file":
        if not path:
            print_error("--path required for --source file")
            raise typer.Exit(1)
        if not path.exists():
            print_error(f"File not found: {path}")
            raise typer.Exit(1)

        resolved_dest.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["unzip", "-o", str(path), "-d", str(resolved_dest)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print_error(f"Extraction failed: {result.stderr.strip()}")
                raise typer.Exit(1)
            print_success(f"Kit extracted to {resolved_dest}")
        except FileNotFoundError:
            print_error("unzip not found. Install: dnf install unzip")
            raise typer.Exit(1)
    else:
        print_error(f"Unknown source: {source}. Use 'git' or 'file'")
        raise typer.Exit(1)

    # Save kit path to config
    config = get_config()
    config.psa_kit_path = resolved_dest
    config.save()

    # Scaffold DPK_CUST_HOME
    if resolved_cust.exists() and any(resolved_cust.iterdir()):
        print_warning(f"DPK_CUST_HOME already has files, skipping scaffold: {resolved_cust}")
    else:
        print_info("Scaffolding DPK_CUST_HOME...")
        _scaffold_dpk_cust_home(resolved_cust)
        print_success(f"DPK_CUST_HOME scaffolded at {resolved_cust}")

    # Save cust path to config
    config.dpk_cust_home = resolved_cust
    config.save()

    print_success("Kit installation complete")
    print_info("Next: psa dpk sync --dpk-path <path>")


@app.command("update")
def kit_update(
    dest: Optional[Path] = typer.Option(
        None,
        "--dest",
        "-d",
        help="Kit install location",
    ),
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to zip file (for non-git installs)",
    ),
) -> None:
    """
    Update PSA Kit to latest version.

    For git-managed installs, runs git pull. For file-based installs,
    requires --path to a new zip file. Does NOT touch DPK_CUST_HOME.

    Examples:
        psa kit update
        psa kit update --path /tmp/psa-kit-v2.zip
    """
    resolved_dest = _resolve_kit_path(dest)

    if not resolved_dest.exists():
        print_error(f"Kit not installed at: {resolved_dest}")
        print_info("Run 'psa kit install' first")
        raise typer.Exit(1)

    # Auto-detect git
    git_dir = resolved_dest / ".git"
    if git_dir.exists():
        print_info(f"Updating kit (git pull) at {resolved_dest}...")
        try:
            result = subprocess.run(
                ["git", "pull"],
                cwd=str(resolved_dest),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print_error(f"Git pull failed: {result.stderr.strip()}")
                raise typer.Exit(1)
            print_success(f"Kit updated: {result.stdout.strip()}")
        except FileNotFoundError:
            print_error("git not found")
            raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            print_error("Git pull timed out")
            raise typer.Exit(1)
    elif path:
        if not path.exists():
            print_error(f"File not found: {path}")
            raise typer.Exit(1)
        print_info(f"Updating kit from {path}...")
        try:
            result = subprocess.run(
                ["unzip", "-o", str(path), "-d", str(resolved_dest)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print_error(f"Extraction failed: {result.stderr.strip()}")
                raise typer.Exit(1)
            print_success("Kit updated from zip")
        except FileNotFoundError:
            print_error("unzip not found. Install: dnf install unzip")
            raise typer.Exit(1)
    else:
        print_error("Not a git install. Use --path to provide a zip file")
        raise typer.Exit(1)


@app.command("status")
def kit_status(
    dest: Optional[Path] = typer.Option(
        None,
        "--dest",
        "-d",
        help="Kit install location",
    ),
) -> None:
    """
    Show PSA Kit installation status.

    Displays version, paths, source type, and available modules.

    Examples:
        psa kit status
    """
    resolved_dest = _resolve_kit_path(dest)
    config = get_config()
    resolved_cust = config.dpk_cust_home or Path(DEFAULT_DPK_CUST_HOME)

    console.print("[bold]PSA Kit Status[/bold]\n")

    if not resolved_dest.exists():
        console.print(f"  Kit path: {resolved_dest}")
        print_warning("Kit not installed")
        print_info("Run 'psa kit install' to set up")
        return

    console.print(f"  Kit path: [cyan]{resolved_dest}[/cyan]")

    # Source type
    git_dir = resolved_dest / ".git"
    if git_dir.exists():
        console.print("  Source: git")
        # Show git info
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                cwd=str(resolved_dest),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                console.print(f"  Version: [cyan]{result.stdout.strip()}[/cyan]")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                cwd=str(resolved_dest),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                console.print(f"  Last commit: {result.stdout.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    else:
        console.print("  Source: file")

    # DPK_CUST_HOME path
    console.print(f"  DPK_CUST_HOME: [cyan]{resolved_cust}[/cyan]")
    if resolved_cust.exists():
        console.print("  DPK_CUST_HOME exists: [green]yes[/green]")
    else:
        console.print("  DPK_CUST_HOME exists: [yellow]no[/yellow]")

    # List io_* modules
    modules_dir = resolved_dest / "dpk" / "puppet" / "production" / "modules"
    if modules_dir.exists():
        io_modules = sorted(
            d.name for d in modules_dir.iterdir()
            if d.is_dir() and d.name.startswith("io_")
        )
        if io_modules:
            console.print(f"\n  Modules ({len(io_modules)}):")
            for m in io_modules:
                console.print(f"    - {m}")
        else:
            console.print("\n  [dim]No io_* modules found[/dim]")
    else:
        console.print("\n  [dim]Modules directory not found[/dim]")
