"""psa dpk module: install and list bolt-on Puppet modules in DPK_CUST_HOME."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from psa.core.config import DEFAULT_DPK_CUST_HOME, get_config
from psa.core.output import print_error, print_info, print_success, print_warning

console = Console()

REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
NAME_PATTERN = re.compile(r"^[\w.][\w.-]*$")
GITHUB_HTTPS = "https://github.com/{repo}.git"

app = typer.Typer(
    name="module",
    help="Manage bolt-on Puppet modules in DPK_CUST_HOME/modules/",
    no_args_is_help=True,
)


def _resolve_dpk_cust_home(path: Optional[Path]) -> Path:
    """Resolve DPK_CUST_HOME: --dpk-cust-home -> $DPK_CUST_HOME -> config -> default."""
    if path:
        return path.resolve()
    if env := os.environ.get("DPK_CUST_HOME"):
        return Path(env)
    config = get_config()
    if config.dpk_cust_home:
        return config.dpk_cust_home
    return Path(DEFAULT_DPK_CUST_HOME)


def _git(args: List[str], cwd: Optional[Path] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command, capturing output."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@app.command("install")
def install(
    repos: List[str] = typer.Argument(
        ...,
        help="One or more GitHub org/repo strings (e.g., psadmin-io/io_role)",
    ),
    dpk_cust_home: Optional[Path] = typer.Option(
        None,
        "--dpk-cust-home",
        "-c",
        help="DPK_CUST_HOME (or $DPK_CUST_HOME, or config.dpk_cust_home)",
    ),
    branch: str = typer.Option(
        "main",
        "--branch",
        help="Git branch to clone",
    ),
    as_name: Optional[str] = typer.Option(
        None,
        "--as",
        help="Override target directory name (only valid with a single repo)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be cloned without cloning",
    ),
) -> None:
    """
    Clone one or more Puppet modules from GitHub via HTTPS.

    Modules are cloned shallow (--depth 1) into <DPK_CUST_HOME>/modules/<repo_name>/.
    By default the target dir is the repo's name (puppetlabs/puppetlabs-inifile -> puppetlabs-inifile).
    Use --as to override (e.g. for Puppet's modulepath, which expects bare module names).
    If a module directory already exists, it is skipped (no overwrite).

    Examples:
        psa dpk module install psadmin-io/io_role
        psa dpk module install psadmin-io/io_role psadmin-io/io_portalwar
        psa dpk module install psadmin-io/io_role --branch develop
        psa dpk module install puppetlabs/puppetlabs-inifile --as inifile
        psa dpk module install psadmin-io/io_role --dry-run
    """
    if as_name is not None:
        if len(repos) != 1:
            print_error("--as requires exactly one repo argument")
            raise typer.Exit(1)
        if not NAME_PATTERN.match(as_name):
            print_error(f"Invalid --as name: {as_name!r} (allowed: letters, digits, '_', '-', '.')")
            raise typer.Exit(1)

    dpk_cust = _resolve_dpk_cust_home(dpk_cust_home)
    modules_dir = dpk_cust / "modules"

    print_info(f"Installing modules to {modules_dir}...")

    installed = 0
    skipped = 0
    failed = 0

    for repo in repos:
        if not REPO_PATTERN.match(repo):
            console.print(f"  [red]✗[/red] {repo} — invalid org/repo format")
            failed += 1
            continue

        repo_name = as_name if as_name else repo.split("/", 1)[1]
        target = modules_dir / repo_name

        if target.exists() and any(target.iterdir()):
            console.print(f"  [yellow]⊘[/yellow] {repo_name} — already exists, skipping")
            skipped += 1
            continue

        if dry_run:
            console.print(f"  [dim]Would clone: {repo} → {target}[/dim]")
            installed += 1
            continue

        # Ensure modules dir exists
        try:
            modules_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            print_error(f"Permission denied creating: {modules_dir}")
            raise typer.Exit(1)

        url = GITHUB_HTTPS.format(repo=repo)
        try:
            result = _git(
                ["clone", "--depth", "1", "--branch", branch, url, str(target)],
                timeout=120,
            )
        except FileNotFoundError:
            print_error("git not found. Install git first")
            raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            console.print(f"  [red]✗[/red] {repo_name} — clone timed out")
            failed += 1
            # Clean up partial dir
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            continue

        if result.returncode == 0:
            console.print(f"  [green]✓[/green] {repo_name} ({repo})")
            installed += 1
        else:
            console.print(f"  [red]✗[/red] {repo_name} — {result.stderr.strip()}")
            failed += 1
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)

    # Summary
    parts = []
    if installed:
        parts.append(f"{installed} installed")
    if skipped:
        parts.append(f"{skipped} skipped")
    if failed:
        parts.append(f"{failed} failed")
    summary = ", ".join(parts) if parts else "no action"
    console.print(f"{summary}.")

    if failed:
        raise typer.Exit(1)


def _module_info(module_dir: Path) -> dict:
    """Collect git metadata for a module directory."""
    info = {"name": module_dir.name, "git": False, "remote": None, "branch": None, "commit": None}
    if not (module_dir / ".git").exists():
        return info
    info["git"] = True
    try:
        r = _git(["remote", "get-url", "origin"], cwd=module_dir, timeout=5)
        if r.returncode == 0:
            info["remote"] = r.stdout.strip()
        r = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=module_dir, timeout=5)
        if r.returncode == 0:
            info["branch"] = r.stdout.strip()
        r = _git(["rev-parse", "--short", "HEAD"], cwd=module_dir, timeout=5)
        if r.returncode == 0:
            info["commit"] = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return info


def _shorten_remote(remote: Optional[str]) -> Optional[str]:
    """Reduce 'https://github.com/foo/bar.git' or 'git@github.com:foo/bar.git' to 'foo/bar'."""
    if not remote:
        return None
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?$", remote)
    return m.group(1) if m else remote


@app.command("list")
def list_modules(
    dpk_cust_home: Optional[Path] = typer.Option(
        None,
        "--dpk-cust-home",
        "-c",
        help="DPK_CUST_HOME (or $DPK_CUST_HOME, or config.dpk_cust_home)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
) -> None:
    """
    List installed bolt-on modules in DPK_CUST_HOME/modules/.

    For each git-managed module, shows the remote, branch, and short commit.

    Examples:
        psa dpk module list
        psa dpk module list --json
    """
    dpk_cust = _resolve_dpk_cust_home(dpk_cust_home)
    modules_dir = dpk_cust / "modules"

    if not modules_dir.exists():
        if json_output:
            console.print_json(json.dumps({"path": str(modules_dir), "modules": []}))
            return
        print_warning(f"Modules directory not found: {modules_dir}")
        return

    modules = [
        _module_info(d)
        for d in sorted(modules_dir.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    ]

    if json_output:
        console.print_json(json.dumps({"path": str(modules_dir), "modules": modules}))
        return

    if not modules:
        console.print(f"[dim]No modules found in {modules_dir}[/dim]")
        return

    console.print(f"Modules in {modules_dir}:")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Source", style="white")
    table.add_column("Branch @ commit", style="dim")

    for m in modules:
        if m["git"]:
            short = _shorten_remote(m["remote"]) or "(unknown)"
            ref = f"{m['branch']} @ {m['commit']}" if m["branch"] and m["commit"] else "-"
            table.add_row(m["name"], short, ref)
        else:
            table.add_row(m["name"], "[yellow]not a git repo[/yellow]", "-")

    console.print(table)
    console.print(f"{len(modules)} module(s).")
