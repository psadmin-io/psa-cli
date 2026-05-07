"""DPK lifecycle management commands."""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import List, NamedTuple, Optional, Union

import typer
from rich.console import Console

from psa.core.config import PsaConfig, get_config
from psa.core.fileops import SudoFileOps
from psa.core.output import print_error, print_info, print_json, print_success, print_warning
from psa.core.subprocess_runner import print_stderr_on_failure, stream_subprocess

console = Console()

# DPK prerequisite libraries: ncurses .5 family expected by Oracle's bundled
# Python/Ruby and the DPK setup script. EL 7/8 ship these via ncurses-compat-libs;
# EL 9+ omits the package and we symlink the .6 libs (ncurses-libs) instead.
NCURSES_LIB_NAMES = [
    "libncursesw.so.5",
    "libtinfo.so.5",
    "libncurses.so.5",
    "libform.so.5",
    "libpanel.so.5",
    "libmenu.so.5",
]

LIB_SEARCH_DIRS = ["/usr/lib64", "/lib64"]

OS_RELEASE_PATH = "/etc/os-release"

# Tuxedo/OUI prerequisite libraries (for middleware installs)
# Note: Actual requirements vary by OS version
TUXEDO_REQUIRED_LIBS = {
    "libaio.so.1": ["/lib64/libaio.so.1", "/usr/lib64/libaio.so.1"],
    "libnsl.so.1": ["/lib64/libnsl.so.1", "/usr/lib64/libnsl.so.1"],
}


class FixAction(NamedTuple):
    description: str
    command: List[str]

# Patterns to detect first DPK zip (in priority order)
FIRST_ZIP_PATTERNS = [
    "*_1of*.zip",  # Oracle delivery: PT862_1of5.zip
    "*-01.zip",  # MOS download: V123456-01.zip
    "*_1.zip",  # Alternate: PTDPK_1.zip
]

# Environment variable names
ENV_DPK_REPO = "DPK_REPO"
ENV_DPK_INSTALL = "DPK_INSTALL"
ENV_DPK_BASE = "DPK_BASE"  # Parent dir, used by Oracle's DPK setup script
ENV_DPK_HOME = "DPK_HOME"  # The DPK install dir itself, = DPK_BASE/dpk

# Defaults
DEFAULT_DPK_BASE = "/u01/app/psoft"
DEFAULT_DPK_HOME = "/u01/app/psoft/dpk"

def _generate_hiera_yaml(
    dpk_cust_home: Optional[Path],
    psa_kit_path: Optional[Path],
    enable_psa_kit: bool = False,
) -> str:
    """Generate hiera.yaml hierarchy: DPK_CUST_HOME -> [KIT] -> DPK base.

    Customer and kit layers use absolute datadir paths so Puppet reads from
    those locations. DPK layers use relative paths (the default data dir).
    Kit layer is only emitted when enable_psa_kit=True.
    """
    lines = [
        "---",
        "version: 5",
        "",
        "defaults:",
        "  datadir: data",
        "  data_hash: yaml_data",
        "",
        "hierarchy:",
    ]

    # --- Customer layer (absolute datadir) ---
    if dpk_cust_home:
        cust_datadir = str(dpk_cust_home / "data")
        lines += [
            f'  - name: "Per-domain customizations"',
            f'    datadir: "{cust_datadir}"',
            f'    path: "domain/%{{facts.domainname}}.yaml"',
            "",
            f'  - name: "Per-server customizations"',
            f'    datadir: "{cust_datadir}"',
            f'    path: "server/%{{facts.hostname}}.yaml"',
            "",
            f'  - name: "Environment-level config"',
            f'    datadir: "{cust_datadir}"',
            f'    path: "environment/%{{facts.env}}.yaml"',
            "",
            f'  - name: "Tier-level config"',
            f'    datadir: "{cust_datadir}"',
            f'    path: "tier/%{{facts.ps_tier}}.yaml"',
            "",
            f'  - name: "Zone-role config"',
            f'    datadir: "{cust_datadir}"',
            f'    path: "zone/%{{facts.ps_zone}}-%{{facts.ps_role}}.yaml"',
            "",
            f'  - name: "Common customizations"',
            f'    datadir: "{cust_datadir}"',
            f'    path: "common.yaml"',
            "",
        ]

    # --- Kit layer (absolute datadir) ---
    if enable_psa_kit and psa_kit_path:
        kit_datadir = str(psa_kit_path / "dpk" / "puppet" / "production" / "data")
        lines += [
            f'  - name: "psa-ops common"',
            f'    datadir: "{kit_datadir}"',
            f'    path: "psa-ops/common.yaml"',
            "",
        ]

    # --- DPK base layers (relative, uses default datadir) ---
    lines += [
        '  # Delivered DPK YAML files (Oracle defaults)',
        '  - name: "DPK configuration"',
        '    path: "psft_configuration.yaml"',
        "",
        '  - name: "DPK customizations"',
        '    path: "psft_customizations.yaml"',
        "",
        '  - name: "DPK unix system"',
        '    path: "psft_unix_system.yaml"',
        "",
        '  - name: "DPK deployment"',
        '    path: "psft_deployment.yaml"',
        "",
        '  - name: "DPK patches"',
        '    path: "psft_patches.yaml"',
        "",
        '  - name: "DPK defaults"',
        '    path: "defaults.yaml"',
    ]

    return "\n".join(lines) + "\n"

# Role -> class included by site.pp. Source of truth for both the rendered
# manifest below and the role-resolution announcement in `psa dpk apply`.
ROLE_CLASS_MAP = {
    "app": "io_role::io_tools_appserver",
    "appbat": "io_role::io_tools_appbatch",
    "web": "io_role::io_tools_pia",
    "prcs": "io_role::io_tools_prcs",
    "mid": "io_role::io_tools_midtier",
    "webapp": "io_role::io_tools_webapp",
}


def _render_site_pp() -> str:
    lines = ["node default {", "  case $facts[ps_role] {"]
    for role, cls in ROLE_CLASS_MAP.items():
        key = f"'{role}':"
        lines.append(f"    {key:<13} {{ include ::{cls} }}")
    lines += ["  }", "}", ""]
    return "\n".join(lines)


SITE_PP_TEMPLATE = _render_site_pp()


class DeployType(str, Enum):
    """DPK deploy type - what software to install."""

    all = "all"
    tools_home = "tools_home"
    app_home = "app_home"
    app_and_tools_home = "app_and_tools_home"


app = typer.Typer(
    name="dpk",
    help="Manage DPK lifecycle",
    no_args_is_help=True,
)


def _resolve_puppet_bin(resolved_path: Path) -> Path:
    """Locate the puppet binary or exit with a friendly message.

    Search order: DPK-bundled agent, /opt/puppetlabs, then $PATH.
    """
    dpk_base = resolved_path.parent  # e.g., /opt/oracle/psft
    dpk_puppet = dpk_base / "psft_puppet_agent" / "bin" / "puppet"
    if dpk_puppet.exists():
        return dpk_puppet
    if Path("/opt/puppetlabs/puppet/bin/puppet").exists():
        return Path("/opt/puppetlabs/puppet/bin/puppet")
    try:
        result = subprocess.run(["which", "puppet"], capture_output=True, text=True)
        if result.returncode == 0:
            candidate = Path(result.stdout.strip())
            if candidate.exists():
                return candidate
    except FileNotFoundError:
        pass
    print_error("Puppet not found. Run 'psa dpk setup' first")
    print_info(f"Expected at: {dpk_puppet}")
    raise typer.Exit(1)


def _build_facter_env(
    config: PsaConfig,
    server_facts: dict,
    *,
    env: Optional[str],
    tier: Optional[str],
    pillar: Optional[str],
    zone: Optional[str],
    role: Optional[str],
) -> tuple[dict, list]:
    """Resolve fact precedence (CLI > server.yaml > config default) and
    build a FACTER_*-populated env dict.

    Only sets FACTER_* when the value comes from a CLI flag or config
    default; if server.yaml supplies the fact, leaves FACTER_* unset so
    Facter reads server.yaml directly. Side effect: prints
    `Reading from server.yaml: ...` and `Setting fact: ...` info lines.

    Returns (facter_env, defaulted_messages).
    """
    ops = config.ops

    cli_provided = {
        "env": env is not None,
        "ps_tier": tier is not None,
        "ps_pillar": pillar is not None,
        "ps_zone": zone is not None,
        "ps_role": role is not None,
    }

    defaulted: list = []
    if not env and "env" not in server_facts and ops.environment_name:
        env = ops.environment_name
        defaulted.append(f"env={env}")
    if not tier and "ps_tier" not in server_facts and ops.tier:
        tier = ops.tier
        defaulted.append(f"tier={tier}")
    if not pillar and "ps_pillar" not in server_facts and ops.pillar:
        pillar = ops.pillar
        defaulted.append(f"pillar={pillar}")
    if not zone and "ps_zone" not in server_facts and ops.zone:
        zone = ops.zone
        defaulted.append(f"zone={zone}")
    if not role and "ps_role" not in server_facts and ops.ps_role:
        role = ops.ps_role
        defaulted.append(f"role={role}")

    server_provided = [
        k for k in ("ps_role", "env", "ps_tier", "ps_zone", "ps_pillar")
        if k in server_facts
    ]
    if server_provided:
        print_info(f"Reading from server.yaml: {', '.join(server_provided)}")

    facter_env = os.environ.copy()

    def _set(fact: str, value: Optional[str]) -> None:
        if not value:
            return
        if (
            not cli_provided.get(fact, False)
            and fact in server_facts
            and value == server_facts.get(fact)
        ):
            return
        facter_env[f"FACTER_{fact}"] = value
        print_info(f"Setting fact: {fact}={value}")

    _set("env", env)
    _set("ps_tier", tier)
    _set("ps_pillar", pillar)
    _set("ps_zone", zone)
    _set("ps_role", role)

    return facter_env, defaulted


def _wrap_with_sudo(
    cmd: list,
    facter_env: dict,
    config: PsaConfig,
) -> tuple[list, dict]:
    """Auto-sudo a puppet command unless we're already root, running as the
    configured runtime_user, or sudo is disabled.

    sudo strips env by default; lift FACTER_* into VAR=val args (the form
    sudo recognizes for the target command) when sudo'ing. Returns
    (final_cmd, run_env).
    """
    user = os.environ.get("USER")
    needs_sudo = (
        config.sudo_enabled
        and os.geteuid() != 0
        and user != config.runtime_user
    )
    if not needs_sudo:
        return cmd, facter_env

    facter_args = [
        f"{k}={v}" for k, v in facter_env.items() if k.startswith("FACTER_")
    ]
    return ["sudo"] + facter_args + list(cmd), os.environ.copy()


def _read_server_facts(config: PsaConfig) -> dict:
    """Read facts from <facts.d>/server.yaml. Empty dict if missing or unreadable.

    Searches the same standard system paths as `psa dpk facts` writes to
    (FACTS_D_CANDIDATES from facts.py). Server identity lives in /etc/, not
    the DPK install tree.
    """
    import yaml as _yaml

    from psa.commands.dpk.facts import FACTS_D_CANDIDATES
    from psa.core.fileops import SudoFileOps

    candidates = [Path(d) / "server.yaml" for d in FACTS_D_CANDIDATES]
    fileops = SudoFileOps(config)
    for candidate in candidates:
        content = fileops.read_text(candidate)
        if content is None:
            continue
        try:
            data = _yaml.safe_load(content)
        except _yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _get_env_path(env_var: str, cli_value: Optional[Path]) -> Optional[Path]:
    """Get path from CLI arg, environment variable, config, or default.

    For DPK_BASE: cli -> $DPK_BASE -> config.dpk_base -> DEFAULT_DPK_BASE.
    """
    if cli_value:
        return cli_value
    env_val = os.environ.get(env_var)
    if env_val:
        return Path(env_val)
    if env_var == ENV_DPK_BASE:
        cfg = get_config()
        if cfg.dpk_base:
            return cfg.dpk_base
        return Path(DEFAULT_DPK_BASE)
    return None


def _resolve_dpk_home(cli_value: Optional[Path]) -> Path:
    """Resolve DPK_HOME (the dpk install dir).

    Order: cli -> $DPK_HOME -> config.dpk_base/dpk -> DEFAULT_DPK_HOME.
    """
    if cli_value:
        return cli_value.resolve()
    if env := os.environ.get(ENV_DPK_HOME):
        return Path(env)
    cfg = get_config()
    if cfg.dpk_base:
        return cfg.dpk_base / "dpk"
    return Path(DEFAULT_DPK_HOME)


def _find_first_zip(directory: Path) -> Optional[Path]:
    """Find the first DPK zip file using known patterns."""
    for pattern in FIRST_ZIP_PATTERNS:
        matches = list(directory.glob(pattern))
        if matches:
            # Sort to get consistent results
            matches.sort()
            return matches[0]
    return None


def _find_setup_script(install_dir: Path) -> Optional[Path]:
    """Find psft-dpk-setup.sh in install directory."""
    possible_scripts = [
        install_dir / "setup" / "psft-dpk-setup.sh",
        install_dir / "dpk" / "setup" / "psft-dpk-setup.sh",
        install_dir / "pt-dpk" / "setup" / "psft-dpk-setup.sh",
    ]
    for script in possible_scripts:
        if script.exists():
            return script
    return None


@app.command("stage")
def stage(
    repo: Optional[Path] = typer.Option(
        None,
        "--repo",
        "-r",
        help=f"Source dir with DPK zip files (or ${ENV_DPK_REPO})",
    ),
    version: Optional[str] = typer.Option(
        None,
        "--version",
        "-V",
        help="DPK version to stage (e.g. 862.04). Requires dpk_repo_path configured.",
    ),
    install_dir: Optional[Path] = typer.Option(
        None,
        "--install-dir",
        "-i",
        help=f"Staging/install directory (or ${ENV_DPK_INSTALL})",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show actions without executing",
    ),
) -> None:
    """
    Stage DPK files: copy zips from repo and extract first archive

    Copies all DPK zip files from the repo directory to the install directory,
    then extracts only the first zip (which contains the setup scripts).

    Environment variables:
        DPK_REPO: Source directory with DPK zip files
        DPK_INSTALL: Staging/install directory

    Examples:
        psa dpk stage --repo /nfs/dpk/pt862 --install-dir /tmp/dpk
        psa dpk stage --version 862.04 --install-dir /tmp/dpk
        export DPK_REPO=/nfs/dpk/pt862 DPK_INSTALL=/tmp/dpk && psa dpk stage
    """
    # Resolve repo path: --repo > --version via DpkRepo > $DPK_REPO > latest in configured repo
    repo_path = _get_env_path(ENV_DPK_REPO, repo)

    if not repo_path and (version or not os.environ.get(ENV_DPK_REPO)):
        # Try resolving via DpkRepo
        config = get_config()
        if config.dpk_repo_path:
            from psa.core.dpk_repo import DpkRepo

            dpk_repo = DpkRepo(Path(config.dpk_repo_path))
            try:
                repo_path = dpk_repo.resolve_version(version)
                print_info(f"Resolved from DPK repo: {repo_path}")
            except (FileNotFoundError, ValueError) as e:
                print_error(str(e))
                raise typer.Exit(1)
        elif version:
            print_error("--version requires dpk_repo_path. Run: psa dpk repo init --path <path>")
            raise typer.Exit(1)
    install_path = _get_env_path(ENV_DPK_INSTALL, install_dir)

    if not repo_path:
        print_error(f"Repo not specified. Use --repo or set ${ENV_DPK_REPO}")
        raise typer.Exit(1)

    if not install_path:
        print_error(f"Install dir not specified. Use --install-dir or set ${ENV_DPK_INSTALL}")
        raise typer.Exit(1)

    if not repo_path.exists():
        print_error(f"Repo directory not found: {repo_path}")
        raise typer.Exit(1)

    print_info(f"DPK Repo: {repo_path}")
    print_info(f"Install Dir: {install_path}")

    # Find all zip files in repo
    zip_files = list(repo_path.glob("*.zip"))
    if not zip_files:
        print_error(f"No zip files found in: {repo_path}")
        raise typer.Exit(1)

    print_info(f"Found {len(zip_files)} zip file(s)")

    # Create install directory
    if not install_path.exists():
        if dry_run:
            console.print(f"[dim]Would create: {install_path}[/dim]")
        else:
            try:
                install_path.mkdir(parents=True, exist_ok=True)
                print_success(f"Created: {install_path}")
            except PermissionError:
                print_error(f"Permission denied creating: {install_path}")
                raise typer.Exit(1)

    # Copy zip files
    print_info("Copying zip files...")
    for zip_file in sorted(zip_files):
        dest = install_path / zip_file.name
        if dry_run:
            console.print(f"[dim]Would copy: {zip_file.name}[/dim]")
        else:
            if dest.exists():
                print_info(f"  Skip (exists): {zip_file.name}")
            else:
                shutil.copy2(zip_file, dest)
                print_success(f"  Copied: {zip_file.name}")

    # Find and extract first zip (dry-run: search source since files aren't copied yet)
    search_dir = repo_path if dry_run else install_path
    first_zip = _find_first_zip(search_dir)
    if not first_zip:
        print_error("Could not identify first DPK zip file")
        print_info("Expected patterns: *_1of*.zip, *-01.zip, *_1.zip")
        raise typer.Exit(1)

    print_info(f"Extracting first zip: {first_zip.name}")
    dest_zip = install_path / first_zip.name
    unzip_cmd = ["unzip", "-o", str(dest_zip), "-d", str(install_path)]

    if dry_run:
        console.print(f"[dim]Would run: {' '.join(unzip_cmd)}[/dim]")
    else:
        try:
            result = subprocess.run(
                unzip_cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                print_error(f"Unzip failed: {result.stderr}")
                raise typer.Exit(1)
            print_success("First archive extracted")
        except subprocess.TimeoutExpired:
            print_error("Extraction timed out")
            raise typer.Exit(1)
        except FileNotFoundError:
            print_error("unzip not found. Install: dnf install unzip")
            raise typer.Exit(1)

    # Verify setup script exists
    if not dry_run:
        setup_script = _find_setup_script(install_path)
        if setup_script:
            print_success(f"Setup script found: {setup_script}")
        else:
            print_warning("Setup script not found - check extraction")

    print_success("DPK staging complete")
    print_info(f"Next: psa dpk setup --install-dir {install_path} --base-dir <path>")


@app.command("setup")
def setup(
    install_dir: Optional[Path] = typer.Option(
        None,
        "--install-dir",
        "-i",
        help=f"DPK install directory (or ${ENV_DPK_INSTALL})",
    ),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        "-b",
        help=f"PeopleSoft base directory (or ${ENV_DPK_BASE}, default: {DEFAULT_DPK_BASE})",
    ),
    deploy_type: DeployType = typer.Option(
        DeployType.all,
        "--deploy-type",
        "-t",
        help="What to install: all (PS_HOME+middleware) or tools_home (PS_HOME only)",
    ),
    log_file: Optional[Path] = typer.Option(
        None,
        "--log-file",
        "-l",
        help="Log file location",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable Puppet debug output",
    ),
    do_prereq: bool = typer.Option(
        False,
        "--prereq",
        help="Run prerequisite check only (root). Replaces old 'psa dpk prereq'.",
    ),
    do_postcfg: bool = typer.Option(
        False,
        "--postcfg",
        help="Run post-configuration only (root). Replaces old 'psa dpk postcfg'.",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Auto-install missing prerequisites without prompting",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show command without executing",
    ),
) -> None:
    """
    Install DPK software (PS_HOME and middleware)

    Installs PeopleTools and middleware (Tuxedo, WebLogic, DB client) without
    configuring domains. Use 'psa dpk apply' to deploy domains after setup.

    Use --prereq to run prerequisite check (root only, replaces 'psa dpk prereq').
    Use --postcfg to run post-configuration (root only, replaces 'psa dpk postcfg').

    Environment variables:
        DPK_INSTALL: Staging/install directory
        DPK_BASE: PeopleSoft base directory (default: /u01/app/psoft)

    Examples:
        psa dpk setup --base-dir /u01/psft
        psa dpk setup --deploy-type tools_home
        psa dpk setup --prereq --install-dir /tmp/dpk
        psa dpk setup --postcfg --base-dir /u01/psft
    """
    # --prereq and --postcfg are mutually exclusive
    if do_prereq and do_postcfg:
        print_error("--prereq and --postcfg are mutually exclusive")
        raise typer.Exit(1)

    # --- prereq mode ---
    if do_prereq:
        install_path = _get_env_path(ENV_DPK_INSTALL, install_dir)
        if not install_path:
            print_error(f"Install dir not specified. Use --install-dir or set ${ENV_DPK_INSTALL}")
            raise typer.Exit(1)

        # Check our prereqs before Oracle's script
        if not dry_run:
            _check_dpk_prerequisites(fix=fix)

        setup_script = _find_setup_script(install_path)
        if not setup_script:
            print_error("Setup script not found")
            raise typer.Exit(1)

        cmd = [str(setup_script), "--prereq"]
        if os.geteuid() != 0:
            cmd = ["sudo"] + cmd
        print_info(f"Running: {' '.join(cmd)}")

        if dry_run:
            console.print("[dim]Dry run - not executing[/dim]")
            return

        # Pipe "n" to auto-decline Oracle inventory non-root user prompt.
        # subprocess.run(input=) doesn't reliably pass stdin through sudo,
        # so use shell pipe instead.
        shell_cmd = "echo n | " + " ".join(shlex.quote(c) for c in cmd)
        try:
            rc, _, _ = stream_subprocess(
                ["sh", "-c", shell_cmd],
                cwd=setup_script.parent,
                timeout=600,
            )
            if rc == 0:
                print_success("Prerequisites check completed")
            else:
                print_error(f"Prerequisites check failed (exit {rc})")
                raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            print_error("Prereq check timed out")
            raise typer.Exit(1)
        return

    # --- postcfg mode ---
    if do_postcfg:
        install_path = _get_env_path(ENV_DPK_INSTALL, install_dir)
        base_path = _get_env_path(ENV_DPK_BASE, base_dir)

        if not install_path:
            print_error(f"Install dir not specified. Use --install-dir or set ${ENV_DPK_INSTALL}")
            raise typer.Exit(1)

        if not base_path:
            print_error(f"Base dir not specified. Use --base-dir or set ${ENV_DPK_BASE}")
            raise typer.Exit(1)

        setup_script = _find_setup_script(install_path)
        if not setup_script:
            print_error("Setup script not found")
            raise typer.Exit(1)

        cmd = [str(setup_script), "--postcfg", "--psft_base_dir", str(base_path)]
        if os.geteuid() != 0:
            cmd = ["sudo"] + cmd
        print_info(f"Running: {' '.join(cmd)}")

        if dry_run:
            console.print("[dim]Dry run - not executing[/dim]")
            return

        try:
            rc, _, _ = stream_subprocess(cmd, cwd=setup_script.parent, timeout=600)
            if rc == 0:
                print_success("Post-configuration completed")
            else:
                print_error(f"Post-configuration failed (exit {rc})")
                raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            print_error("Post-configuration timed out")
            raise typer.Exit(1)
        return

    # --- default setup mode ---
    # Check prerequisites first
    if not dry_run:
        _check_dpk_prerequisites(deploy_type, fix=fix)

    # Resolve paths
    install_path = _get_env_path(ENV_DPK_INSTALL, install_dir)
    base_path = _get_env_path(ENV_DPK_BASE, base_dir)

    if not install_path:
        print_error(f"Install dir not specified. Use --install-dir or set ${ENV_DPK_INSTALL}")
        raise typer.Exit(1)

    if not base_path:
        base_path = Path(DEFAULT_DPK_BASE)
        print_info(f"Using default base dir: {base_path}")

    if not install_path.exists():
        print_error(f"Install directory not found: {install_path}")
        print_info("Run 'psa dpk stage' first")
        raise typer.Exit(1)

    # Find setup script
    setup_script = _find_setup_script(install_path)
    if not setup_script:
        print_error("Setup script not found")
        print_info("Expected: setup/psft-dpk-setup.sh in install directory")
        raise typer.Exit(1)

    print_info(f"Install Dir: {install_path}")
    print_info(f"Base Dir: {base_path}")
    print_info(f"Deploy Type: {deploy_type.value}")
    print_info(f"Setup Script: {setup_script}")

    # Generate response file for silent mode
    # Oracle setup script requires response file to pass psft_base_dir non-interactively
    response_content = f"""env_type=midtier
psft_base_dir="{base_path}"
user_home_dir="/home"
db_platform=ORACLE
db_is_unicode=true
deploy_only=true
deploy_type={deploy_type.value}
"""

    # Create temporary response file
    response_file_fd, response_file_path = tempfile.mkstemp(
        suffix=".txt", prefix="dpk_response_", text=True
    )
    try:
        with os.fdopen(response_file_fd, "w") as f:
            f.write(response_content)

        print_info(f"Response File: {response_file_path}")

        # Build command - use silent mode with response file
        cmd = [str(setup_script), "--silent", f"--response_file={response_file_path}"]

        if log_file:
            cmd.extend(["--log_file", str(log_file)])

        if debug:
            cmd.append("--debug")

        if os.geteuid() != 0:
            cmd = ["sudo"] + cmd

        print_info(f"Command: {' '.join(cmd)}")
        print_info("Domains will NOT be configured - use 'psa dpk apply' after setup")

        if dry_run:
            console.print("[dim]Dry run - not executing[/dim]")
            print_info(f"Response file content:\n{response_content}")
            return

        # Run setup script
        try:
            rc, _, _ = stream_subprocess(
                cmd,
                cwd=setup_script.parent,
                timeout=7200,  # 2 hour timeout
            )
            if rc == 0:
                print_success("DPK setup completed successfully")
                print_info(f"Next: psa dpk apply --dpk-home {base_path / 'dpk'}")
            else:
                print_error(f"DPK setup failed (exit {rc})")
                raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            print_error("Setup timed out (>2 hours)")
            raise typer.Exit(1)
        except PermissionError:
            print_error(f"Permission denied: {setup_script}")
            print_info("Try running with sudo or as root")
            raise typer.Exit(1)
    finally:
        # Clean up temporary response file
        if os.path.exists(response_file_path):
            os.unlink(response_file_path)


@app.command("cleanup")
def cleanup(
    install_dir: Optional[Path] = typer.Option(
        None,
        "--install-dir",
        "-i",
        help=f"DPK install directory (or ${ENV_DPK_INSTALL})",
    ),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        "-b",
        help=f"PeopleSoft base directory (or ${ENV_DPK_BASE})",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show command without executing",
    ),
) -> None:
    """
    Clean up DPK installation

    Runs the DPK cleanup script to remove installed software and components.
    Wrapper for: ./psft-dpk-setup.sh --cleanup --psft_base_dir <path>

    Examples:
        psa dpk cleanup --base-dir /u01/psft
        psa dpk cleanup --dry-run
    """
    # Resolve paths
    install_path = _get_env_path(ENV_DPK_INSTALL, install_dir)
    base_path = _get_env_path(ENV_DPK_BASE, base_dir)

    if not install_path:
        print_error(f"Install dir not specified. Use --install-dir or set ${ENV_DPK_INSTALL}")
        raise typer.Exit(1)

    if not base_path:
        print_error(f"Base dir not specified. Use --base-dir or set ${ENV_DPK_BASE}")
        raise typer.Exit(1)

    # Find setup script
    setup_script = _find_setup_script(install_path)
    if not setup_script:
        print_error("Setup script not found")
        print_info("Run 'psa dpk stage' first or specify correct --install-dir")
        raise typer.Exit(1)

    print_warning(f"This will clean up DPK installation at: {base_path}")
    print_info(f"Setup Script: {setup_script}")

    # Build command
    cmd = [str(setup_script), "--cleanup", "--psft_base_dir", str(base_path)]
    if os.geteuid() != 0:
        cmd = ["sudo"] + cmd

    print_info(f"Running: {' '.join(cmd)}")

    if dry_run:
        console.print("[dim]Dry run - not executing[/dim]")
        return

    try:
        rc, _, _ = stream_subprocess(cmd, cwd=setup_script.parent, timeout=600)
        if rc == 0:
            print_success("DPK cleanup completed")
        else:
            print_error(f"Cleanup failed (exit {rc})")
            raise typer.Exit(1)
    except subprocess.TimeoutExpired:
        print_error("Cleanup timed out")
        raise typer.Exit(1)


@app.command("status")
def status(
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
) -> None:
    """
    Check DPK installation status

    Verifies:
    - Puppet is installed and accessible
    - Hiera configuration exists
    - DPK modules are available
    - PeopleTools manifest (version + middleware)

    Examples:
        psa dpk status
        psa dpk status --json
    """
    if not json_output:
        print_info("Checking DPK status...")

    # Check Puppet
    if json_output:
        puppet_info = _verify_puppet(exit_on_fail=False, quiet=True)
        puppet_ok = puppet_info["installed"]
    else:
        puppet_ok = _verify_puppet(exit_on_fail=False)

    # Check common DPK locations: env var, configured base, then well-known paths
    dpk_paths = [
        _get_env_path(ENV_DPK_BASE, None),
        Path("/u01/app/psoft/dpk"),
        Path("/opt/dpk"),
        Path("/home/psadm2/dpk"),
    ]
    dpk_paths = [p for p in dpk_paths if p is not None]

    dpk_found = None
    for path in dpk_paths:
        if path.exists() and (path / "puppet").exists():
            dpk_found = path
            break

    hiera_ok = False
    site_ok = False
    manifest_data = None

    if dpk_found:
        if not json_output:
            print_success(f"DPK found: {dpk_found}")

        # Parse manifest
        manifest_path = dpk_found / "pt-manifest"
        if manifest_path.exists():
            manifest_data = _parse_manifest(manifest_path)
            if not json_output:
                pt_ver = manifest_data.get("version", "unknown")
                print_success(f"PeopleTools: {pt_ver}")
                for label, key in [
                    ("Oracle Client", "oracleclient_version"),
                    ("JDK", "jdk_version"),
                    ("WebLogic", "weblogic_version"),
                    ("Tuxedo", "tuxedo_version"),
                ]:
                    val = manifest_data.get(key)
                    if val:
                        print_info(f"  {label}: {val}")

        # Check for hiera.yaml
        hiera_yaml = dpk_found / "puppet" / "production" / "hiera.yaml"
        hiera_ok = hiera_yaml.exists()
        if not json_output:
            if hiera_ok:
                print_success(f"Hiera config: {hiera_yaml}")
            else:
                print_warning("Hiera config not found")

        # Check for site.pp
        site_pp = dpk_found / "puppet" / "production" / "manifests" / "site.pp"
        site_ok = site_pp.exists()
        if not json_output:
            if site_ok:
                print_success(f"Site manifest: {site_pp}")
            else:
                print_warning("Site manifest not found")
    else:
        if not json_output:
            print_warning("DPK installation not found in standard locations")

    ready = puppet_ok and dpk_found is not None

    if json_output:
        data = {
            "puppet": puppet_info,
            "dpk": {"found": dpk_found is not None, "path": str(dpk_found) if dpk_found else None},
            "manifest": manifest_data,
            "hiera": hiera_ok,
            "site_manifest": site_ok,
            "ready": ready,
        }
        print_json(data)
    else:
        if ready:
            print_success("DPK is ready for provisioning")
        else:
            print_warning("DPK setup incomplete")


@app.command("apply")
def apply(
    role: Optional[str] = typer.Option(
        None,
        "--role",
        "-r",
        help="Set ps_role fact (app, web, prcs, mid, webapp)",
    ),
    env: Optional[str] = typer.Option(
        None,
        "--env",
        "-e",
        help="Set env fact for Hiera lookup (e.g., FSCMDEV)",
    ),
    tier: Optional[str] = typer.Option(
        None,
        "--tier",
        "-t",
        help="Set ps_tier fact for Hiera lookup (e.g., DEV)",
    ),
    pillar: Optional[str] = typer.Option(
        None,
        "--pillar",
        "-p",
        help="Set ps_pillar fact for Hiera lookup (e.g., FSCM, HCM)",
    ),
    zone: Optional[str] = typer.Option(
        None,
        "--zone",
        "-z",
        help="Set ps_zone fact for Hiera lookup (e.g., nonprod, prod, dr)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Puppet dry run (noop mode)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Puppet debug output",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Stream full puppet output (Info/Debug lines included)",
    ),
    dpk_home: Optional[Path] = typer.Option(
        None,
        "--dpk-home",
        "-d",
        help=f"DPK install dir (or ${ENV_DPK_HOME}, or config.dpk_base/dpk; default {DEFAULT_DPK_HOME})",
    ),
) -> None:
    """
    Apply DPK configuration

    Applies Puppet manifests to configure PeopleSoft domains.
    Requires DPK to be set up first.

    Examples:
        psa dpk apply
        psa dpk apply --role app
        psa dpk apply --env FSCMDEV --tier DEV
        psa dpk apply --dry-run
        psa dpk apply --verbose
    """
    # Resolve DPK_HOME (the dpk install dir)
    resolved_path = _resolve_dpk_home(dpk_home)

    # Verify paths exist
    puppet_dir = resolved_path / "puppet"
    if not puppet_dir.exists():
        print_error(f"DPK puppet directory not found: {puppet_dir}")
        print_info("Run 'psa dpk setup' first")
        raise typer.Exit(1)

    site_pp = puppet_dir / "production" / "manifests" / "site.pp"

    if not site_pp.exists():
        print_error(f"Site manifest not found: {site_pp}")
        raise typer.Exit(1)

    puppet_bin = _resolve_puppet_bin(resolved_path)

    cmd = [
        str(puppet_bin),
        "apply",
        "--confdir",
        str(puppet_dir),
        "--environment",
        "production",
        # Without this puppet exits 0 on every "noop with changes" or
        # resource failure, masking real problems. See exit-code mapping below.
        "--detailed-exitcodes",
        str(site_pp),
    ]

    if dry_run:
        cmd.append("--noop")  # Puppet's flag is --noop

    if debug:
        cmd.append("--debug")

    # Load config and read server.yaml (Facter external facts).
    config = get_config()
    server_facts = _read_server_facts(config)
    facter_env, defaulted = _build_facter_env(
        config, server_facts,
        env=env, tier=tier, pillar=pillar, zone=zone, role=role,
    )
    if defaulted and not config.ops.suppress_fact_warnings:
        print_warning(f"Using config defaults: {', '.join(defaulted)}")

    # Role -> class announcement. The "0.03s catalog compile" silent-failure
    # case usually reduces to: ps_role didn't match any case in site.pp, so
    # nothing was included.
    effective_role = role or server_facts.get("ps_role") or config.ops.ps_role
    if effective_role:
        cls = ROLE_CLASS_MAP.get(effective_role)
        if cls:
            print_info(f"Resolved ps_role={effective_role} -> {cls}")
        else:
            print_warning(
                f"ps_role={effective_role!r} does not match any class in site.pp "
                f"(known: {', '.join(ROLE_CLASS_MAP)}). Catalog will be empty."
            )
    else:
        print_warning(
            "ps_role is not set (no --role, no server.yaml, no config default). "
            "Catalog will be empty."
        )

    cmd, run_env = _wrap_with_sudo(cmd, facter_env, config)

    print_info(f"Running: {' '.join(cmd)}")

    stdout_filter = None if verbose else _puppet_default_filter
    try:
        rc, stdout_text, stderr_text = stream_subprocess(
            cmd,
            cwd=puppet_dir,
            env=run_env,
            timeout=3600,
            stdout_filter=stdout_filter,
        )
    except subprocess.TimeoutExpired:
        print_error("Puppet apply timed out (>1 hour)")
        raise typer.Exit(1)
    except FileNotFoundError:
        print_error("Puppet not found. Run 'psa dpk setup' first")
        raise typer.Exit(1)

    _emit_catalog_diagnostics(stdout_text, rc, dry_run)

    # Stderr-error scan trumps exit code. Puppet --noop with --detailed-exitcodes
    # has been observed to exit 0 even when catalog compilation hits errors
    # like missing Hiera keys; the error appears on stderr but the resource-state
    # exit code says "no changes". Search for known fatal patterns and override.
    stderr_errors = _scan_puppet_errors(stderr_text)
    if stderr_errors:
        print_error(
            f"Puppet apply failed: {len(stderr_errors)} error(s) detected on stderr "
            f"(exit {rc} ignored)"
        )
        raise typer.Exit(1)

    if rc == 0:
        print_success("Puppet apply: no changes needed")
    elif rc == 2 and dry_run:
        print_success("Puppet apply: would make changes (dry-run)")
    elif rc == 2:
        print_success("Puppet apply: changes applied")
    elif rc == 4:
        print_error("Puppet apply completed with resource failures")
        raise typer.Exit(1)
    elif rc == 6:
        print_error("Puppet apply applied changes but had resource failures")
        raise typer.Exit(1)
    elif rc == 1:
        print_error("Puppet apply failed: catalog compilation or parse error")
        raise typer.Exit(1)
    else:
        print_error(f"Puppet apply failed (exit {rc})")
        raise typer.Exit(rc if rc > 0 else 1)


@app.command("lookup")
def lookup(
    key: str = typer.Argument(..., help="Hiera key to look up (e.g. oracle_client_version)"),
    render_as: str = typer.Option(
        "yaml",
        "--render-as",
        help="Output format: yaml | json | s",
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Show the hierarchy walk and which level (if any) matched",
    ),
    role: Optional[str] = typer.Option(
        None, "--role", "-r",
        help="Set ps_role fact (app, web, prcs, mid, webapp)",
    ),
    env: Optional[str] = typer.Option(
        None, "--env", "-e",
        help="Set env fact for Hiera lookup (e.g., FSCMDEV)",
    ),
    tier: Optional[str] = typer.Option(
        None, "--tier", "-t",
        help="Set ps_tier fact for Hiera lookup",
    ),
    pillar: Optional[str] = typer.Option(
        None, "--pillar", "-p",
        help="Set ps_pillar fact for Hiera lookup",
    ),
    zone: Optional[str] = typer.Option(
        None, "--zone", "-z",
        help="Set ps_zone fact for Hiera lookup",
    ),
    dpk_home: Optional[Path] = typer.Option(
        None, "--dpk-home",
        help=f"DPK install dir (or ${ENV_DPK_HOME}, or config.dpk_base/dpk; default {DEFAULT_DPK_HOME})",
    ),
) -> None:
    """
    Look up a Hiera key using the same facts apply would use.

    Wraps `puppet lookup`. Useful for debugging "why does apply think X is
    Y?" or "where should I define this missing key?"

    Examples:
        psa dpk lookup oracle_client_version --env FSCMDEV --role mid
        psa dpk lookup pia_psserver_list --explain
        psa dpk lookup db_settings --render-as json
    """
    resolved_path = _resolve_dpk_home(dpk_home)
    puppet_dir = resolved_path / "puppet"
    if not puppet_dir.exists():
        print_error(f"DPK puppet directory not found: {puppet_dir}")
        print_info("Run 'psa dpk setup' first")
        raise typer.Exit(1)

    puppet_bin = _resolve_puppet_bin(resolved_path)

    config = get_config()
    server_facts = _read_server_facts(config)
    facter_env, defaulted = _build_facter_env(
        config, server_facts,
        env=env, tier=tier, pillar=pillar, zone=zone, role=role,
    )
    if defaulted and not config.ops.suppress_fact_warnings:
        print_warning(f"Using config defaults: {', '.join(defaulted)}")

    cmd = [
        str(puppet_bin), "lookup", key,
        "--confdir", str(puppet_dir),
        "--environment", "production",
        "--render-as", render_as,
    ]
    if explain:
        cmd.append("--explain")

    cmd, run_env = _wrap_with_sudo(cmd, facter_env, config)
    print_info(f"Running: {' '.join(cmd)}")

    try:
        rc, _, _ = stream_subprocess(
            cmd, cwd=puppet_dir, env=run_env, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print_error("Puppet lookup timed out (>2 min)")
        raise typer.Exit(1)
    except FileNotFoundError:
        print_error("Puppet not found. Run 'psa dpk setup' first")
        raise typer.Exit(1)

    # puppet lookup exits non-zero when the key is undefined; pass through.
    if rc != 0:
        raise typer.Exit(rc)


# Lines starting with these prefixes are puppet's chatty output. By default
# we drop them; --verbose passes everything through.
_PUPPET_QUIET_PREFIXES = ("Info:", "Debug:")


def _puppet_default_filter(line: str) -> bool:
    return not line.lstrip().startswith(_PUPPET_QUIET_PREFIXES)


_CATALOG_COMPILE_RE = re.compile(r"Compiled catalog .* in ([\d.]+) seconds")
_NOTICE_CHANGE_RE = re.compile(r"^Notice: /Stage\[", re.MULTILINE)

# Patterns whose presence on stderr means the run failed, regardless of the
# exit code puppet reported. See https://puppet.com/docs/puppet/latest/man/apply.html
# - puppet --noop with --detailed-exitcodes can exit 0 while emitting these.
_PUPPET_FATAL_STDERR_RES = [
    re.compile(r"^Error:", re.MULTILINE),
    re.compile(r"Function lookup\(\) did not find"),
    re.compile(r"Could not find class"),
    re.compile(r"Could not parse"),
    re.compile(r"Evaluation Error"),
]


def _scan_puppet_errors(stderr_text: str) -> list[str]:
    """Return stderr lines matching any fatal puppet error pattern."""
    if not stderr_text:
        return []
    matches: list[str] = []
    for line in stderr_text.splitlines():
        if any(p.search(line) for p in _PUPPET_FATAL_STDERR_RES):
            matches.append(line)
    return matches


def _emit_catalog_diagnostics(stdout_text: str, rc: int, dry_run: bool) -> None:
    """Surface change counts and warn about suspiciously fast compiles."""
    match = _CATALOG_COMPILE_RE.search(stdout_text)
    if match:
        compile_s = float(match.group(1))
        if compile_s < 0.5 and rc in (0, 2):
            print_warning(
                f"Catalog compiled in {compile_s}s - unusually fast; the role "
                f"class may not have loaded. Check that ps_role matches a class "
                f"in site.pp and that all required Hiera keys are defined."
            )

    changes = len(_NOTICE_CHANGE_RE.findall(stdout_text))
    if changes:
        verb = "Would change" if dry_run else "Changed"
        print_info(f"{verb}: {changes} resources")


def _detect_os_major_version() -> Optional[int]:
    """Parse the major VERSION_ID from /etc/os-release. Returns int or None."""
    try:
        text = Path(OS_RELEASE_PATH).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VERSION_ID="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            try:
                return int(value.split(".")[0])
            except (ValueError, IndexError):
                return None
    return None


def _find_lib(name: str) -> Optional[Path]:
    """Return the path to a system library if found in any LIB_SEARCH_DIRS."""
    for d in LIB_SEARCH_DIRS:
        p = Path(d) / name
        if p.exists():
            return p
    return None


def _sudo_prefix() -> List[str]:
    return [] if os.geteuid() == 0 else ["sudo"]


def _plan_ncurses_fix(
    missing: List[str], os_major: Optional[int]
) -> List[FixAction]:
    """Plan fix actions for missing ncurses .5 libs based on OS version."""
    if not missing:
        return []

    # EL 7/8 (or unknown): ncurses-compat-libs covers all .5 libs in one shot
    if os_major is None or os_major < 9:
        cmd = _sudo_prefix() + ["dnf", "install", "-y", "ncurses-compat-libs"]
        return [FixAction("Install ncurses-compat-libs", cmd)]

    # EL 9+: per-lib symlink to the .6 from ncurses-libs
    actions: List[FixAction] = []
    needs_libs = any(
        _find_lib(name.replace(".so.5", ".so.6")) is None for name in missing
    )
    if needs_libs:
        cmd = _sudo_prefix() + ["dnf", "install", "-y", "ncurses-libs"]
        actions.append(FixAction("Install ncurses-libs (provides .6 libs)", cmd))

    for name in missing:
        target_name = name.replace(".so.5", ".so.6")
        target = _find_lib(target_name) or Path("/usr/lib64") / target_name
        link = target.parent / name
        cmd = _sudo_prefix() + ["ln", "-s", str(target), str(link)]
        actions.append(FixAction(f"Symlink {name} -> {target.name}", cmd))

    return actions


def _check_dpk_prerequisites(
    deploy_type: DeployType = DeployType.all, fix: bool = False
) -> None:
    """Check DPK prerequisites; with --fix, install/symlink missing libs.

    On EL 9+ the .5 ncurses libs are not packaged; falls back to symlinking
    the existing .6 libs (from ncurses-libs). On EL 7/8 installs ncurses-compat-libs.
    """
    os_major = _detect_os_major_version()

    missing_ncurses = [n for n in NCURSES_LIB_NAMES if _find_lib(n) is None]

    missing_tuxedo: List[str] = []
    if deploy_type != DeployType.tools_home:
        for lib_name, lib_paths in TUXEDO_REQUIRED_LIBS.items():
            if not any(Path(p).exists() for p in lib_paths):
                missing_tuxedo.append(lib_name)

    if not missing_ncurses and not missing_tuxedo:
        print_success("DPK prerequisites OK")
        return

    print_error("Missing DPK prerequisites:")
    for lib in missing_ncurses:
        console.print(f"  [red]✗[/red] {lib}")
    for lib in missing_tuxedo:
        console.print(f"  [red]✗[/red] {lib}")
    console.print()

    ncurses_actions = _plan_ncurses_fix(missing_ncurses, os_major)
    if ncurses_actions and os_major is not None and os_major >= 9:
        print_info(
            f"On EL {os_major}+, ncurses-compat-libs is not packaged; "
            "fix uses symlinks to existing .6 libs."
        )

    if ncurses_actions:
        print_info("Fix plan:")
        for action in ncurses_actions:
            console.print(f"  [cyan]{' '.join(action.command)}[/cyan]")

    pkg_map = {"libaio.so.1": "libaio", "libnsl.so.1": "libnsl"}
    tuxedo_pkgs = [pkg_map[n] for n in missing_tuxedo if n in pkg_map]
    tuxedo_cmd: Optional[List[str]] = None
    if tuxedo_pkgs:
        tuxedo_cmd = _sudo_prefix() + ["dnf", "install", "-y"] + tuxedo_pkgs
        print_info(f"Install command: [cyan]{' '.join(tuxedo_cmd)}[/cyan]")

    console.print()
    should_fix = fix
    if not fix:
        should_fix = typer.confirm("Apply fixes?")

    if not should_fix:
        raise typer.Exit(1)

    for action in ncurses_actions:
        print_info(f"Running: {' '.join(action.command)}")
        result = subprocess.run(action.command)
        if result.returncode != 0:
            print_error(f"Failed: {action.description}")
            print_info(f"Run manually: {' '.join(action.command)}")
            raise typer.Exit(1)

    if tuxedo_cmd:
        print_info(f"Running: {' '.join(tuxedo_cmd)}")
        result = subprocess.run(tuxedo_cmd)
        if result.returncode != 0:
            print_error("Package install failed")
            raise typer.Exit(1)

    print_success("Prerequisites installed")


def _parse_manifest(manifest_path: Path) -> dict:
    """Parse a DPK manifest file (key=value format)."""
    data = {}
    for line in manifest_path.read_text().strip().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            data[key.strip()] = value.strip()
    return data


def _verify_puppet(exit_on_fail: bool = True, quiet: bool = False) -> Union[bool, dict]:
    """Verify DPK relocatable Puppet is installed and accessible.

    When quiet=True, suppress prints and return a dict instead of bool.
    """
    dpk_base = _get_env_path(ENV_DPK_BASE, None) or Path(DEFAULT_DPK_BASE)
    puppet_bin = dpk_base / "psft_puppet_agent" / "bin" / "puppet"

    if puppet_bin.exists():
        try:
            result = subprocess.run(
                [str(puppet_bin), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                if quiet:
                    return {"installed": True, "path": str(puppet_bin), "version": version}
                print_success(f"Puppet installed: {puppet_bin} (v{version})")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if quiet:
        return {"installed": False, "path": str(puppet_bin), "version": None}

    if exit_on_fail:
        print_error("Puppet not found or not working")
        raise typer.Exit(1)

    print_warning("Puppet not found")
    return False


# --- Helper functions for sync command ---


def _default_fileops() -> SudoFileOps:
    """Direct-mode SudoFileOps for callers (e.g. tests) that don't inject one."""
    return SudoFileOps(PsaConfig(sudo_enabled=False))


def _write_with_escalation(path: Path, content: str, fileops: SudoFileOps) -> bool:
    """Try writing as runtime_user, then escalate to root.

    DPK_HOME is often root-owned (Oracle's psft-dpk-setup.sh runs as root),
    in which case sudo'ing as runtime_user (psadm2) still can't write. Fall
    back to `sudo bash -c` for those cases.
    """
    if fileops.write_text(path, content):
        return True
    return fileops.write_text(path, content, as_root=True)


def _backup_and_write(
    target: Path, content: str, fileops: SudoFileOps
) -> bool:
    """Back up `target` to .bak (if it exists) then write `content`. Sudo-aware."""
    backup = target.with_suffix(target.suffix + ".bak")
    existing = fileops.read_text(target)
    if existing is not None:
        if not _write_with_escalation(backup, existing, fileops):
            print_error(f"Failed to back up {target} -> {backup}")
            if getattr(fileops, "last_error", None):
                print_info(fileops.last_error)
            return False
    if not _write_with_escalation(target, content, fileops):
        print_error(f"Failed to write {target}")
        if getattr(fileops, "last_error", None):
            print_info(fileops.last_error)
        return False
    return True


def _deploy_hiera_files(
    dpk_path: Path,
    dpk_cust_home: Optional[Path] = None,
    psa_kit_path: Optional[Path] = None,
    dry_run: bool = False,
    enable_psa_kit: bool = False,
    fileops: Optional[SudoFileOps] = None,
) -> bool:
    """Deploy hiera.yaml to puppet directories. Returns True on success."""
    puppet_dir = dpk_path / "puppet"
    if not puppet_dir.exists():
        print_error(f"Puppet directory not found: {puppet_dir}")
        return False

    if fileops is None:
        fileops = _default_fileops()

    hiera_content = _generate_hiera_yaml(dpk_cust_home, psa_kit_path, enable_psa_kit)

    targets = [
        puppet_dir / "hiera.yaml",
        puppet_dir / "production" / "hiera.yaml",
    ]

    for target in targets:
        target_dir = target.parent
        if not target_dir.exists():
            continue

        if dry_run:
            if target.exists():
                console.print(f"  [dim]Would backup: {target.name}[/dim]")
            console.print(f"  [dim]Would write: {target}[/dim]")
        else:
            if not _backup_and_write(target, hiera_content, fileops):
                return False
            print_success(f"  hiera.yaml -> {target.parent.name}/")

    return True


def _deploy_site_pp(
    dpk_path: Path,
    dry_run: bool = False,
    fileops: Optional[SudoFileOps] = None,
) -> bool:
    """Deploy site.pp to manifests directory. Returns True on success."""
    manifests_dir = dpk_path / "puppet" / "production" / "manifests"
    if not manifests_dir.exists():
        print_error(f"Manifests directory not found: {manifests_dir}")
        return False

    if fileops is None:
        fileops = _default_fileops()

    target = manifests_dir / "site.pp"

    if dry_run:
        if target.exists():
            console.print(f"  [dim]Would backup: {target.name}[/dim]")
        console.print(f"  [dim]Would write: {target}[/dim]")
    else:
        if not _backup_and_write(target, SITE_PP_TEMPLATE, fileops):
            return False
        print_success("  site.pp -> manifests/")

    return True


def _generate_environment_conf(
    dpk_cust_home: Optional[Path],
    psa_kit_path: Optional[Path],
    dpk_base_path: Path,
    enable_psa_kit: bool = False,
) -> str:
    """Generate environment.conf for the production Puppet directory environment.

    modulepath: DPK_CUST_HOME/modules : [KIT modules :] DPK/puppet/production/modules
    Kit segment only when enable_psa_kit=True.
    """
    dpk_modules = str(dpk_base_path / "puppet" / "production" / "modules")

    parts = []
    if dpk_cust_home:
        parts.append(str(dpk_cust_home / "modules"))
    if enable_psa_kit and psa_kit_path:
        parts.append(str(psa_kit_path / "dpk" / "puppet" / "production" / "modules"))
    parts.append(dpk_modules)

    modulepath = ":".join(parts)

    return (
        f"modulepath = {modulepath}\n"
        "manifest = manifests/site.pp\n"
        "environment_timeout = unlimited\n"
    )


def _deploy_environment_conf(
    dpk_path: Path,
    dpk_cust_home: Optional[Path] = None,
    psa_kit_path: Optional[Path] = None,
    dry_run: bool = False,
    enable_psa_kit: bool = False,
    fileops: Optional[SudoFileOps] = None,
) -> bool:
    """Deploy environment.conf to the production env dir. Returns True on success."""
    env_dir = dpk_path / "puppet" / "production"
    if not env_dir.exists():
        print_error(f"Puppet environment directory not found: {env_dir}")
        return False

    if fileops is None:
        fileops = _default_fileops()

    target = env_dir / "environment.conf"
    content = _generate_environment_conf(dpk_cust_home, psa_kit_path, dpk_path, enable_psa_kit)

    if dry_run:
        if target.exists():
            console.print(f"  [dim]Would backup: {target.name}[/dim]")
        console.print(f"  [dim]Would write: {target}[/dim]")
    else:
        if not _backup_and_write(target, content, fileops):
            return False
        print_success(f"  environment.conf -> {env_dir.relative_to(dpk_path)}/")

    return True


@app.command("sync")
def sync(
    dpk_home: Optional[Path] = typer.Option(
        None,
        "--dpk-home",
        "-d",
        help=f"DPK install dir (or ${ENV_DPK_HOME}, or config.dpk_base/dpk; default {DEFAULT_DPK_HOME})",
    ),
    dpk_cust_home: Optional[Path] = typer.Option(
        None,
        "--dpk-cust-home",
        "-c",
        help="DPK_CUST_HOME (or $DPK_CUST_HOME, or config.dpk_cust_home)",
    ),
    do_hiera: bool = typer.Option(
        False,
        "--hiera",
        help="Sync hiera.yaml only (default: sync all)",
    ),
    do_site: bool = typer.Option(
        False,
        "--site",
        help="Sync site.pp only (default: sync all)",
    ),
    do_environment_conf: bool = typer.Option(
        False,
        "--environment-conf",
        help="Sync environment.conf only (default: sync all)",
    ),
    sync_data: bool = typer.Option(
        False,
        "--data",
        hidden=True,
        help="Sync Hiera data from PSA-OPS (replaces 'psa dpk data sync')",
    ),
    tier: Optional[str] = typer.Option(
        None,
        "--tier",
        "-t",
        hidden=True,
        help="Tier for data sync (with --data)",
    ),
    environments: Optional[str] = typer.Option(
        None,
        "--environments",
        "-e",
        hidden=True,
        help="Environments for data sync, comma-separated (with --data)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
) -> None:
    """
    Refresh generated config files in DPK_HOME so Puppet picks up DPK_CUST_HOME.

    Writes hiera.yaml, site.pp, and environment.conf into DPK_HOME/puppet/.
    Modules are no longer copied here — install them into DPK_CUST_HOME/modules/
    via 'psa dpk module install'; environment.conf points Puppet's modulepath there.

    Requires 'psa dpk init' to have been run (config.dpk_cust_home must be set).

    Examples:
        psa dpk sync --dpk-home /opt/oracle/psft/dpk
        psa dpk sync --hiera --site
        psa dpk sync --dry-run
        psa dpk sync --dpk-cust-home /u01/app/io/dpk-cust
    """
    # If none of the filter flags specified, sync all
    sync_all = not (do_hiera or do_site or do_environment_conf)

    # Resolve DPK_HOME (the dpk install dir)
    resolved_dpk = _resolve_dpk_home(dpk_home)
    if not resolved_dpk.exists():
        print_error(f"DPK_HOME not found: {resolved_dpk}")
        print_info(f"Set --dpk-home, ${ENV_DPK_HOME}, or config.dpk_base.")
        raise typer.Exit(1)

    # Resolve dpk_cust_home (required): flag -> env -> config
    config = get_config()
    if dpk_cust_home:
        resolved_cust = dpk_cust_home.resolve()
    elif env_cust := os.environ.get("DPK_CUST_HOME"):
        resolved_cust = Path(env_cust)
    else:
        resolved_cust = config.dpk_cust_home
    if not resolved_cust:
        print_error("DPK_CUST_HOME not configured.")
        print_info("Run 'psa dpk init' first, set --dpk-cust-home, or set $DPK_CUST_HOME.")
        raise typer.Exit(1)

    resolved_kit = (
        Path(os.environ["PSA_KIT"]) if os.environ.get("PSA_KIT")
        else config.psa_kit_path
    )

    print_info(f"DPK_HOME: {resolved_dpk}")
    print_info(f"DPK_CUST_HOME: {resolved_cust}")
    if resolved_kit:
        print_info(f"PSA Kit: {resolved_kit}")
    console.print()

    if dry_run:
        console.print("[yellow]Dry run - no changes will be made[/yellow]")
        console.print()

    console.print("[bold]Syncing custom DPK configuration...[/bold]")

    # DPK_HOME is typically owned by runtime_user (psadm2); use sudo if needed.
    fileops = SudoFileOps(config)

    # Deploy hiera.yaml
    if sync_all or do_hiera:
        if not _deploy_hiera_files(
            resolved_dpk, resolved_cust, resolved_kit, dry_run,
            enable_psa_kit=config.enable_psa_kit,
            fileops=fileops,
        ):
            raise typer.Exit(1)

    # Deploy site.pp
    if sync_all or do_site:
        if not _deploy_site_pp(resolved_dpk, dry_run, fileops=fileops):
            raise typer.Exit(1)

    # Deploy environment.conf
    if sync_all or do_environment_conf:
        if not _deploy_environment_conf(
            resolved_dpk, resolved_cust, resolved_kit, dry_run,
            enable_psa_kit=config.enable_psa_kit,
            fileops=fileops,
        ):
            raise typer.Exit(1)

    # Optionally sync OPS data
    if sync_data:
        console.print()
        print_info("Syncing Hiera data from PSA-OPS...")
        from psa.commands.dpk.data import _sync_ops_data

        hiera_path = resolved_dpk / "puppet" / "production" / "data" / "cust"

        try:
            _sync_ops_data(
                tier=tier,
                environments=environments,
                hiera_path=hiera_path,
                dry_run=dry_run,
            )
        except Exception as e:
            print_warning(f"PSA-OPS sync failed: {e}")
            print_info("Run 'psa dpk sync --data' to retry")

    console.print()
    if not dry_run:
        print_success("Custom DPK sync complete")
    print_info("Next: psa dpk apply --role <role>")
