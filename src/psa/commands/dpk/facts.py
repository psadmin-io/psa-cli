"""psa dpk facts: manage Puppet Facter external facts (server identity)."""

import json
import os
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console

from psa.commands.dpk.core import DEFAULT_DPK_BASE, ENV_DPK_BASE
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

FACTS_D_CANDIDATES = [
    "/opt/puppetlabs/facter/facts.d",
    "/etc/facter/facts.d",
]

app = typer.Typer(
    name="facts",
    help="Manage Puppet Facter external facts (server identity)",
    no_args_is_help=True,
)


def _resolve_dpk_base(dpk_path: Optional[Path]) -> Path:
    """Resolve DPK base: --dpk-path -> $DPK_BASE -> default."""
    if dpk_path:
        return dpk_path.resolve()
    if env := os.environ.get(ENV_DPK_BASE):
        return Path(env)
    return Path(DEFAULT_DPK_BASE)


def _resolve_facts_d(dpk_path: Optional[Path]) -> Path:
    """Find the facts.d/ directory.

    Search order:
      1. <dpk_base>/psft_puppet_agent/facter/facts.d/
      2. /opt/puppetlabs/facter/facts.d/
      3. /etc/facter/facts.d/

    Returns the first existing dir, or option (1) if none exist (caller will
    create it on write).
    """
    dpk_base = _resolve_dpk_base(dpk_path)
    primary = dpk_base / "psft_puppet_agent" / "facter" / "facts.d"
    candidates = [primary] + [Path(p) for p in FACTS_D_CANDIDATES]
    for c in candidates:
        if c.exists():
            return c
    return primary


def _server_yaml_path(dpk_path: Optional[Path]) -> Path:
    return _resolve_facts_d(dpk_path) / "server.yaml"


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
    dpk_path: Optional[Path] = typer.Option(
        None,
        "--dpk-path",
        help=f"DPK base path (or ${ENV_DPK_BASE})",
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
    Backs up an existing server.yaml to server.yaml.bak.
    Validates --role against known values.

    Examples:
        psa dpk facts init --role mid --env FSCMDEV --tier DEV --zone nonprod
        psa dpk facts init --role app --env FSCMDEV --tier DEV
        psa dpk facts init --dry-run --role mid
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

    target = _server_yaml_path(dpk_path)
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
    dpk_path: Optional[Path] = typer.Option(
        None,
        "--dpk-path",
        help=f"DPK base path (or ${ENV_DPK_BASE})",
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

    target = _server_yaml_path(dpk_path)
    fileops = SudoFileOps(get_config())

    facts = _read_server_yaml(target, fileops)
    facts[key] = value

    content = _format_server_yaml(facts)
    if not fileops.write_text(target, content, as_root=True):
        print_error(f"Failed to write {target}")
        raise typer.Exit(1)

    print_success(f"Set {key}={value} in {target}")


@app.command("list")
def facts_list(
    dpk_path: Optional[Path] = typer.Option(
        None,
        "--dpk-path",
        help=f"DPK base path (or ${ENV_DPK_BASE})",
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

    Examples:
        psa dpk facts list
        psa dpk facts list --json
    """
    target = _server_yaml_path(dpk_path)
    fileops = SudoFileOps(get_config())
    raw = fileops.read_text(target)

    if raw is None:
        if json_output:
            console.print_json(json.dumps({"path": str(target), "facts": None}))
            raise typer.Exit(1)
        print_warning("No server facts file found.")
        print_info("Run 'psa dpk facts init' to configure server identity.")
        raise typer.Exit(1)

    try:
        data = yaml.safe_load(raw)
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
