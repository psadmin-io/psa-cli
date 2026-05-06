"""psa dpk facts: manage Puppet Facter external facts (server identity)."""

import json
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console

from psa.core.config import get_config
from psa.core.fileops import SudoFileOps
from psa.core.output import print_error, print_info, print_success, print_warning

console = Console()

KNOWN_FACTS = ["ps_role", "env", "ps_tier", "ps_zone", "ps_pillar"]
KNOWN_ROLES = ["app", "appbat", "web", "prcs", "mid", "webapp"]

FACTS_D_HEADER = (
    "# Managed by psa-cli — server identity facts\n"
    "# These facts are read by Facter on every Puppet run.\n"
)

# Standard system facts.d locations searched in order. Server identity belongs
# in /etc, not in the DPK install tree (which gets blown away on reinstall).
FACTS_D_CANDIDATES = [
    "/etc/puppetlabs/facter/facts.d",
    "/etc/facter/facts.d",
]

app = typer.Typer(
    name="facts",
    help="Manage Puppet Facter external facts (server identity)",
    no_args_is_help=True,
)


def _resolve_facts_d(facts_dir: Optional[Path]) -> Path:
    """Resolve the facts.d/ directory.

    If facts_dir is given, use it. Otherwise return the first existing standard
    candidate, or the first candidate if none exist (caller creates it on write).
    """
    if facts_dir:
        return facts_dir.resolve()
    for c in FACTS_D_CANDIDATES:
        p = Path(c)
        if p.exists():
            return p
    return Path(FACTS_D_CANDIDATES[0])


def _server_yaml_path(facts_dir: Optional[Path]) -> Path:
    return _resolve_facts_d(facts_dir) / "server.yaml"


def _find_existing_server_yaml(
    facts_dir: Optional[Path], fileops: SudoFileOps
) -> Optional[Path]:
    """Locate an existing server.yaml across standard paths. None if not found."""
    if facts_dir:
        candidate = facts_dir / "server.yaml"
        return candidate if fileops.read_text(candidate) is not None else None
    for c in FACTS_D_CANDIDATES:
        candidate = Path(c) / "server.yaml"
        if fileops.read_text(candidate) is not None:
            return candidate
    return None


def _read_server_yaml(path: Path, fileops: SudoFileOps) -> dict:
    """Load server.yaml as a dict; empty dict if missing or empty."""
    content = fileops.read_text(path)
    if content is None:
        return {}
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        print_error(f"Failed to parse {path}: {e}")
        raise typer.Exit(1)
    return data if isinstance(data, dict) else {}


def _format_server_yaml(facts: dict) -> str:
    """Build the server.yaml content (header + body)."""
    body = yaml.safe_dump(facts, default_flow_style=False, sort_keys=False) if facts else ""
    return FACTS_D_HEADER + body


@app.command("init")
def facts_init(
    role: Optional[str] = typer.Option(
        None,
        "--role",
        "-r",
        help=f"ps_role ({', '.join(KNOWN_ROLES)})",
    ),
    env: Optional[str] = typer.Option(
        None,
        "--env",
        "-e",
        help="env / environment name (e.g., FSCMDEV)",
    ),
    tier: Optional[str] = typer.Option(
        None,
        "--tier",
        "-t",
        help="ps_tier (e.g., DEV, TST, PRD)",
    ),
    zone: Optional[str] = typer.Option(
        None,
        "--zone",
        "-z",
        help="ps_zone (e.g., nonprod, prod, dr)",
    ),
    pillar: Optional[str] = typer.Option(
        None,
        "--pillar",
        "-p",
        help="ps_pillar (e.g., FSCM, HCM)",
    ),
    facts_dir: Optional[Path] = typer.Option(
        None,
        "--facts-dir",
        help=f"facts.d directory (default: first existing of {', '.join(FACTS_D_CANDIDATES)})",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be written",
    ),
) -> None:
    """
    Initialize the server identity file with the given facts.

    Writes <facts.d>/server.yaml with the explicitly-passed flags only.
    Default location is /etc/puppetlabs/facter/facts.d/server.yaml (Puppet 6+/PE
    convention), falling back to /etc/facter/facts.d/. Override with --facts-dir.
    Backs up an existing server.yaml to server.yaml.bak.
    Validates --role against known values.

    Examples:
        psa dpk facts init --role mid --env FSCMDEV --tier DEV --zone nonprod
        psa dpk facts init --role app --env FSCMDEV --tier DEV
        psa dpk facts init --dry-run --role mid
        psa dpk facts init --role mid --facts-dir /etc/facter/facts.d
    """
    if role is not None and role not in KNOWN_ROLES:
        print_error(f"Unknown role: {role}. Valid: {', '.join(KNOWN_ROLES)}")
        raise typer.Exit(1)

    facts: dict = {}
    if role is not None:
        facts["ps_role"] = role
    if env is not None:
        facts["env"] = env
    if tier is not None:
        facts["ps_tier"] = tier
    if zone is not None:
        facts["ps_zone"] = zone
    if pillar is not None:
        facts["ps_pillar"] = pillar

    if not facts:
        print_error("No facts specified. Pass at least one of --role/--env/--tier/--zone/--pillar")
        raise typer.Exit(1)

    target = _server_yaml_path(facts_dir)
    content = _format_server_yaml(facts)

    print_info(f"Writing server facts to {target}")
    for k, v in facts.items():
        console.print(f"  {k}: {v}")

    if dry_run:
        console.print("[dim]Dry run — content:[/dim]")
        console.print(content)
        return

    fileops = SudoFileOps(get_config())

    # Backup existing
    existing = fileops.read_text(target)
    if existing is not None:
        backup = target.with_suffix(".yaml.bak")
        if not fileops.write_text(backup, existing, as_root=True):
            print_error(f"Failed to back up existing {target} -> {backup}")
            raise typer.Exit(1)

    if not fileops.write_text(target, content, as_root=True):
        print_error(f"Failed to write {target}")
        print_info("Ensure passwordless sudo is configured for the lab user.")
        raise typer.Exit(1)

    print_success("Server identity configured.")


@app.command("set")
def facts_set(
    key: str = typer.Argument(..., help="Fact name (e.g., ps_role)"),
    value: str = typer.Argument(..., help="Fact value"),
    facts_dir: Optional[Path] = typer.Option(
        None,
        "--facts-dir",
        help=f"facts.d directory (default: first existing of {', '.join(FACTS_D_CANDIDATES)})",
    ),
) -> None:
    """
    Set or update a single fact in the server.yaml file.

    If server.yaml exists, the key is updated in place (or added).
    If absent, a new file is created with just this key.
    Unknown keys are allowed but produce a warning.

    Examples:
        psa dpk facts set ps_role mid
        psa dpk facts set env FSCMDEV
        psa dpk facts set ps_tier DEV
    """
    if key not in KNOWN_FACTS:
        print_warning(f"Unknown fact key: {key} (allowed but not in standard set: {', '.join(KNOWN_FACTS)})")

    fileops = SudoFileOps(get_config())
    # Update an existing file in place if found anywhere; otherwise create at default
    target = _find_existing_server_yaml(facts_dir, fileops) or _server_yaml_path(facts_dir)

    facts = _read_server_yaml(target, fileops)
    facts[key] = value

    content = _format_server_yaml(facts)
    if not fileops.write_text(target, content, as_root=True):
        print_error(f"Failed to write {target}")
        raise typer.Exit(1)

    print_success(f"Set {key}={value} in {target}")


@app.command("list")
def facts_list(
    facts_dir: Optional[Path] = typer.Option(
        None,
        "--facts-dir",
        help=f"facts.d directory (default: search {', '.join(FACTS_D_CANDIDATES)})",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
) -> None:
    """
    Show the current server identity from facts.d/server.yaml.

    Searches /etc/puppetlabs/facter/facts.d/ then /etc/facter/facts.d/ unless
    --facts-dir is specified.

    Examples:
        psa dpk facts list
        psa dpk facts list --json
    """
    fileops = SudoFileOps(get_config())
    target = _find_existing_server_yaml(facts_dir, fileops)

    if target is None:
        searched = (
            [str(facts_dir / "server.yaml")]
            if facts_dir
            else [f"{p}/server.yaml" for p in FACTS_D_CANDIDATES]
        )
        if json_output:
            console.print_json(json.dumps({"path": None, "facts": None, "searched": searched}))
            raise typer.Exit(1)
        print_warning("No server.yaml found. Searched:")
        for p in searched:
            console.print(f"  {p}")
        print_info("Run 'psa dpk facts init' to configure server identity.")
        raise typer.Exit(1)

    raw = fileops.read_text(target)
    try:
        data = yaml.safe_load(raw) if raw else {}
    except yaml.YAMLError as e:
        print_error(f"Failed to parse {target}: {e}")
        raise typer.Exit(1)

    if not isinstance(data, dict):
        data = {}

    if json_output:
        console.print_json(json.dumps({"path": str(target), "facts": data}))
        return

    console.print(f"Server facts ({target}):")
    if not data:
        console.print("  [dim](empty)[/dim]")
        return
    for k, v in data.items():
        console.print(f"  {k}: {v}")
