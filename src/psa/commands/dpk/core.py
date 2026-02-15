"""DPK lifecycle management commands."""

import os
import shutil
import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from psa.core.config import get_config
from psa.core.output import print_error, print_info, print_success, print_warning

console = Console()

# DPK prerequisite libraries
DPK_REQUIRED_LIBS = [
    "/lib64/libncursesw.so.5",
    "/usr/lib64/libncursesw.so.5",
]

# Tuxedo/OUI prerequisite libraries (for middleware installs)
# Note: Actual requirements vary by OS version
TUXEDO_REQUIRED_LIBS = {
    "libaio.so.1": ["/lib64/libaio.so.1", "/usr/lib64/libaio.so.1"],
}

# Patterns to detect first DPK zip (in priority order)
FIRST_ZIP_PATTERNS = [
    "*_1of*.zip",  # Oracle delivery: PT862_1of5.zip
    "*-01.zip",  # MOS download: V123456-01.zip
    "*_1.zip",  # Alternate: PTDPK_1.zip
]

# Environment variable names
ENV_DPK_REPO = "DPK_REPO"
ENV_DPK_INSTALL = "DPK_INSTALL"
ENV_DPK_BASE = "DPK_BASE"

# Defaults
DEFAULT_DPK_BASE = "/u01/app/psoft"

def _generate_hiera_yaml(psa_cust_path: Optional[Path], psa_kit_path: Optional[Path]) -> str:
    """Generate hiera.yaml with 3-tier hierarchy: CUST -> KIT -> DPK base.

    Customer and kit layers use absolute datadir paths so Puppet reads from
    those locations. DPK layers use relative paths (the default data dir).
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
    if psa_cust_path:
        cust_datadir = str(psa_cust_path / "dpk" / "puppet" / "production" / "data")
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
            f'    path: "env/%{{facts.env}}.yaml"',
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
    if psa_kit_path:
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

# psa-ops site.pp template (role-based node classification)
SITE_PP_TEMPLATE = """\
node default {
  case $facts[ps_role] {
    'app':        { include ::io_role::io_tools_appserver }
    'appbat':     { include ::io_role::io_tools_appbatch }
    'web':        { include ::io_role::io_tools_pia }
    'prcs':       { include ::io_role::io_tools_prcs }
    'mid':        { include ::io_role::io_tools_midtier }
    'webapp':     { include ::io_role::io_tools_webapp }
  }
}
"""


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


def _get_env_path(env_var: str, cli_value: Optional[Path]) -> Optional[Path]:
    """Get path from CLI arg, environment variable, or default."""
    if cli_value:
        return cli_value
    env_val = os.environ.get(env_var)
    if env_val:
        return Path(env_val)
    # Return default for DPK_BASE
    if env_var == ENV_DPK_BASE:
        return Path(DEFAULT_DPK_BASE)
    return None


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

        try:
            result = subprocess.run(cmd, cwd=setup_script.parent, timeout=600, input="n\n", text=True)
            if result.returncode == 0:
                print_success("Prerequisites check completed")
            else:
                print_error(f"Prerequisites check failed (exit {result.returncode})")
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
            result = subprocess.run(cmd, cwd=setup_script.parent, timeout=600)
            if result.returncode == 0:
                print_success("Post-configuration completed")
            else:
                print_error(f"Post-configuration failed (exit {result.returncode})")
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
            result = subprocess.run(
                cmd,
                cwd=setup_script.parent,
                timeout=7200,  # 2 hour timeout
            )
            if result.returncode == 0:
                print_success("DPK setup completed successfully")
                print_info(f"Next: psa dpk apply --dpk-path {base_path}")
            else:
                print_error(f"DPK setup failed (exit {result.returncode})")
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
        result = subprocess.run(cmd, cwd=setup_script.parent, timeout=600)
        if result.returncode == 0:
            print_success("DPK cleanup completed")
        else:
            print_error(f"Cleanup failed (exit {result.returncode})")
            raise typer.Exit(1)
    except subprocess.TimeoutExpired:
        print_error("Cleanup timed out")
        raise typer.Exit(1)


@app.command("status")
def status() -> None:
    """
    Check DPK installation status

    Verifies:
    - Puppet is installed and accessible
    - Hiera configuration exists
    - DPK modules are available

    Examples:
        psa dpk status
    """
    print_info("Checking DPK status...")

    # Check Puppet
    puppet_ok = _verify_puppet(exit_on_fail=False)

    # Check common DPK locations
    dpk_paths = [
        Path(os.environ.get(ENV_DPK_BASE, DEFAULT_DPK_BASE)),
        Path("/u01/app/psoft/dpk"),
        Path("/opt/dpk"),
        Path("/home/psadm2/dpk"),
    ]

    dpk_found = None
    for path in dpk_paths:
        if path.exists() and (path / "puppet").exists():
            dpk_found = path
            break

    if dpk_found:
        print_success(f"DPK found: {dpk_found}")

        # Check for hiera.yaml
        hiera_yaml = dpk_found / "puppet" / "production" / "hiera.yaml"
        if hiera_yaml.exists():
            print_success(f"Hiera config: {hiera_yaml}")
        else:
            print_warning("Hiera config not found")

        # Check for site.pp
        site_pp = dpk_found / "puppet" / "production" / "manifests" / "site.pp"
        if site_pp.exists():
            print_success(f"Site manifest: {site_pp}")
        else:
            print_warning("Site manifest not found")
    else:
        print_warning("DPK installation not found in standard locations")

    if puppet_ok and dpk_found:
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
    dpk_path: Path = typer.Option(
        None,
        "--dpk-path",
        help=f"Path to DPK installation (or ${ENV_DPK_BASE})",
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
        psa dpk apply --debug
    """
    # Resolve DPK path
    resolved_path = _get_env_path(ENV_DPK_BASE, dpk_path)
    if not resolved_path:
        resolved_path = Path(DEFAULT_DPK_BASE)

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

    # Find puppet binary - check DPK location first, then system
    puppet_bin = None
    dpk_base = resolved_path.parent  # e.g., /opt/oracle/psft
    dpk_puppet = dpk_base / "psft_puppet_agent" / "bin" / "puppet"
    if dpk_puppet.exists():
        puppet_bin = dpk_puppet
    elif Path("/opt/puppetlabs/puppet/bin/puppet").exists():
        puppet_bin = Path("/opt/puppetlabs/puppet/bin/puppet")
    else:
        # Try PATH
        try:
            result = subprocess.run(["which", "puppet"], capture_output=True, text=True)
            if result.returncode == 0:
                puppet_bin = Path(result.stdout.strip())
        except FileNotFoundError:
            pass

    if not puppet_bin or not puppet_bin.exists():
        print_error("Puppet not found. Run 'psa dpk setup' first")
        print_info(f"Expected at: {dpk_puppet}")
        raise typer.Exit(1)

    cmd = [
        str(puppet_bin),
        "apply",
        "--confdir",
        str(puppet_dir),
        "--environment",
        "production",
        str(site_pp),
    ]

    if dry_run:
        cmd.append("--noop")  # Puppet's flag is --noop

    if debug:
        cmd.append("--debug")

    # Load config for defaults
    config = get_config()
    ops = config.ops

    # Apply config defaults for unspecified options
    defaulted = []
    if not env and ops.environment_name:
        env = ops.environment_name
        defaulted.append(f"env={env}")
    if not tier and ops.tier:
        tier = ops.tier
        defaulted.append(f"tier={tier}")
    if not pillar and ops.pillar:
        pillar = ops.pillar
        defaulted.append(f"pillar={pillar}")
    if not zone and ops.zone:
        zone = ops.zone
        defaulted.append(f"zone={zone}")
    if not role and ops.ps_role:
        role = ops.ps_role
        defaulted.append(f"role={role}")

    # Show warning for defaulted values (print_warning is verbosity-aware)
    if defaulted and not ops.suppress_fact_warnings:
        print_warning(f"Using config defaults: {', '.join(defaulted)}")

    # Build Facter environment variables
    facter_env = os.environ.copy()

    if env:
        facter_env["FACTER_env"] = env
        print_info(f"Setting fact: env={env}")
    if tier:
        facter_env["FACTER_ps_tier"] = tier
        print_info(f"Setting fact: ps_tier={tier}")
    if pillar:
        facter_env["FACTER_ps_pillar"] = pillar
        print_info(f"Setting fact: ps_pillar={pillar}")
    if zone:
        facter_env["FACTER_ps_zone"] = zone
        print_info(f"Setting fact: ps_zone={zone}")
    if role:
        facter_env["FACTER_ps_role"] = role
        print_info(f"Setting fact: ps_role={role}")

    print_info(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=False,
            timeout=3600,
            cwd=puppet_dir,
            env=facter_env,
        )
        if result.returncode == 0:
            print_success("Puppet apply completed successfully")
        elif result.returncode == 2:
            print_success("Puppet apply completed with changes")
        else:
            print_error(f"Puppet apply failed (exit {result.returncode})")
            raise typer.Exit(1)
    except subprocess.TimeoutExpired:
        print_error("Puppet apply timed out (>1 hour)")
        raise typer.Exit(1)
    except FileNotFoundError:
        print_error("Puppet not found. Run 'psa dpk setup' first")
        raise typer.Exit(1)


def _check_dpk_prerequisites(
    deploy_type: DeployType = DeployType.all, fix: bool = False
) -> None:
    """Check DPK prerequisites are installed. Optionally auto-install missing packages."""
    missing = []
    install_pkgs = []

    # Check for ncurses library (required by DPK bundled Python/Ruby)
    ncurses_found = False
    for lib_path in DPK_REQUIRED_LIBS:
        if Path(lib_path).exists():
            ncurses_found = True
            break

    if not ncurses_found:
        missing.append("libncursesw.so.5")
        install_pkgs.append("ncurses-compat-libs")

    # Check Tuxedo/OUI libs if installing middleware
    if deploy_type != DeployType.tools_home:
        for lib_name, lib_paths in TUXEDO_REQUIRED_LIBS.items():
            lib_found = False
            for lib_path in lib_paths:
                if Path(lib_path).exists():
                    lib_found = True
                    break
            if not lib_found:
                missing.append(lib_name)
                if "libaio" in lib_name:
                    install_pkgs.append("libaio")

    if missing:
        print_error("Missing DPK prerequisites:")
        for lib in missing:
            console.print(f"  [red]✗[/red] {lib}")
        console.print()

        if install_pkgs:
            dnf_cmd = ["dnf", "install", "-y"] + install_pkgs
            if os.geteuid() != 0:
                dnf_cmd = ["sudo"] + dnf_cmd

            should_install = fix
            if not fix:
                print_info(f"Install command: {' '.join(dnf_cmd)}")
                should_install = typer.confirm("Install missing packages?")

            if should_install:
                print_info(f"Running: {' '.join(dnf_cmd)}")
                result = subprocess.run(dnf_cmd)
                if result.returncode != 0:
                    print_error("Package install failed")
                    raise typer.Exit(1)
                print_success("Prerequisites installed")
                return
            else:
                raise typer.Exit(1)

        # Additional guidance for OUI/middleware installs
        if deploy_type != DeployType.tools_home:
            console.print()
            print_warning("Oracle Universal Installer (OUI) may require additional dependencies")
            print_info("For Oracle Linux/RHEL 8+, consider:")
            print_info("  dnf install oracle-database-preinstall-19c")
            print_info("Or check Oracle Support Doc 2617023.1 for PeopleTools prerequisites")

        raise typer.Exit(1)

    print_success("DPK prerequisites OK")


def _verify_puppet(exit_on_fail: bool = True) -> bool:
    """Verify Puppet is installed and accessible."""
    puppet_paths = [
        Path("/opt/puppetlabs/puppet/bin/puppet"),
        Path("/usr/bin/puppet"),
    ]

    puppet_bin = None
    for path in puppet_paths:
        if path.exists():
            puppet_bin = path
            break

    if not puppet_bin:
        try:
            result = subprocess.run(
                ["which", "puppet"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                puppet_bin = Path(result.stdout.strip())
        except FileNotFoundError:
            pass

    if puppet_bin:
        try:
            result = subprocess.run(
                [str(puppet_bin), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                print_success(f"Puppet installed: {puppet_bin} (v{version})")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if exit_on_fail:
        print_error("Puppet not found or not working")
        raise typer.Exit(1)

    print_warning("Puppet not found")
    return False


# --- Helper functions for sync command ---


def _get_source_path(source: Optional[Path]) -> Path:
    """Resolve source path from CLI arg, PSA_KIT env, config, or package location."""
    if source:
        return source.resolve()

    # Check PSA_KIT environment variable
    psa_kit = os.environ.get("PSA_KIT")
    if psa_kit:
        return Path(psa_kit)

    # Check config
    config = get_config()
    if config.psa_kit_path:
        return config.psa_kit_path

    # Fall back to package location (relative to this file)
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _deploy_hiera_files(
    dpk_path: Path,
    psa_cust_path: Optional[Path] = None,
    psa_kit_path: Optional[Path] = None,
    dry_run: bool = False,
) -> bool:
    """Deploy hiera.yaml to puppet directories. Returns True on success."""
    puppet_dir = dpk_path / "puppet"
    if not puppet_dir.exists():
        print_error(f"Puppet directory not found: {puppet_dir}")
        return False

    hiera_content = _generate_hiera_yaml(psa_cust_path, psa_kit_path)

    targets = [
        puppet_dir / "hiera.yaml",
        puppet_dir / "production" / "hiera.yaml",
    ]

    for target in targets:
        target_dir = target.parent
        if not target_dir.exists():
            continue

        backup = target.with_suffix(".yaml.bak")

        if dry_run:
            if target.exists():
                console.print(f"  [dim]Would backup: {target.name}[/dim]")
            console.print(f"  [dim]Would write: {target}[/dim]")
        else:
            if target.exists():
                shutil.copy2(target, backup)
            target.write_text(hiera_content)
            print_success(f"  hiera.yaml -> {target.parent.name}/")

    return True


def _deploy_site_pp(dpk_path: Path, dry_run: bool = False) -> bool:
    """Deploy site.pp to manifests directory. Returns True on success."""
    manifests_dir = dpk_path / "puppet" / "production" / "manifests"
    if not manifests_dir.exists():
        print_error(f"Manifests directory not found: {manifests_dir}")
        return False

    target = manifests_dir / "site.pp"
    backup = target.with_suffix(".pp.bak")

    if dry_run:
        if target.exists():
            console.print(f"  [dim]Would backup: {target.name}[/dim]")
        console.print(f"  [dim]Would write: {target}[/dim]")
    else:
        if target.exists():
            shutil.copy2(target, backup)
        target.write_text(SITE_PP_TEMPLATE)
        print_success("  site.pp -> manifests/")

    return True


def _generate_puppet_conf(
    psa_cust_path: Optional[Path],
    psa_kit_path: Optional[Path],
    dpk_base_path: Path,
) -> str:
    """Generate puppet.conf with 3-tier modulepath: CUST:KIT:DPK modules."""
    dpk_modules = str(dpk_base_path / "puppet" / "production" / "modules")

    parts = []
    if psa_cust_path:
        parts.append(str(psa_cust_path / "dpk" / "puppet" / "production" / "modules"))
    if psa_kit_path:
        parts.append(str(psa_kit_path / "dpk" / "puppet" / "production" / "modules"))
    parts.append(dpk_modules)

    modulepath = ":".join(parts)

    return (
        "[main]\n"
        f"  environmentpath = {dpk_base_path / 'puppet'}\n"
        f"  confdir = {dpk_base_path / 'puppet'}\n"
        "\n"
        "[agent]\n"
        f"  environment = production\n"
        "\n"
        "[user]\n"
        f"  environment = production\n"
        f"  modulepath = {modulepath}\n"
    )


def _deploy_puppet_conf(
    dpk_path: Path,
    psa_cust_path: Optional[Path] = None,
    psa_kit_path: Optional[Path] = None,
    dry_run: bool = False,
) -> bool:
    """Deploy puppet.conf to puppet directory. Returns True on success."""
    puppet_dir = dpk_path / "puppet"
    if not puppet_dir.exists():
        print_error(f"Puppet directory not found: {puppet_dir}")
        return False

    target = puppet_dir / "puppet.conf"
    backup = target.with_suffix(".conf.bak")
    content = _generate_puppet_conf(psa_cust_path, psa_kit_path, dpk_path)

    if dry_run:
        if target.exists():
            console.print(f"  [dim]Would backup: {target.name}[/dim]")
        console.print(f"  [dim]Would write: {target}[/dim]")
    else:
        if target.exists():
            shutil.copy2(target, backup)
        target.write_text(content)
        print_success(f"  puppet.conf -> {puppet_dir.name}/")

    return True


def _deploy_module_files(
    dpk_path: Path, source_path: Path, dry_run: bool = False
) -> bool:
    """Deploy io_profile and io_role modules. Returns True on success."""
    modules_dir = dpk_path / "puppet" / "production" / "modules"
    if not modules_dir.exists():
        print_error(f"Modules directory not found: {modules_dir}")
        return False

    source_modules = source_path / "dpk" / "puppet" / "production" / "modules"
    if not source_modules.exists():
        print_error(f"Source modules not found: {source_modules}")
        return False

    module_names = sorted(
        d.name
        for d in source_modules.iterdir()
        if d.is_dir() and d.name.startswith("io_")
    )
    deployed = 0

    for module_name in module_names:
        source = source_modules / module_name
        target = modules_dir / module_name
        backup = modules_dir / f"{module_name}.bak"

        if not source.exists():
            print_warning(f"  Source module not found: {module_name}")
            continue

        if dry_run:
            if target.exists():
                console.print(f"  [dim]Would backup: {module_name}[/dim]")
            console.print(f"  [dim]Would copy: {module_name}/[/dim]")
        else:
            if target.exists():
                if backup.exists():
                    shutil.rmtree(backup)
                shutil.move(str(target), str(backup))
            shutil.copytree(source, target)
            print_success(f"  {module_name}/ -> modules/")
            deployed += 1

    return deployed > 0 or dry_run


@app.command("sync")
def sync(
    dpk_path: Optional[Path] = typer.Option(
        None,
        "--dpk-path",
        "-d",
        help=f"DPK directory (or ${ENV_DPK_BASE}/dpk)",
    ),
    source: Optional[Path] = typer.Option(
        None,
        "--source",
        "-s",
        help="Source path (or $PSA_KIT)",
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
    do_modules: bool = typer.Option(
        False,
        "--modules",
        help="Sync custom modules only (default: sync all)",
    ),
    do_puppet_conf: bool = typer.Option(
        False,
        "--puppet-conf",
        help="Sync puppet.conf only (default: sync all)",
    ),
    sync_data: bool = typer.Option(
        False,
        "--data",
        help="Sync Hiera data from PSA-OPS (replaces 'psa dpk data sync')",
    ),
    tier: Optional[str] = typer.Option(
        None,
        "--tier",
        "-t",
        help="Tier for data sync (with --data)",
    ),
    environments: Optional[str] = typer.Option(
        None,
        "--environments",
        "-e",
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
    Sync custom DPK files to local installation

    Deploys hiera.yaml, site.pp, and io_profile/io_role modules in one command.
    Use --hiera, --site, or --modules to sync only specific components.
    Use --data to sync Hiera data from PSA-OPS (replaces 'psa dpk data sync').

    Examples:
        psa dpk sync --dpk-path /opt/oracle/psft/dpk
        psa dpk sync --hiera --site
        psa dpk sync --data --tier nonprod
        psa dpk sync --dry-run
    """
    # If none of the filter flags specified, sync all
    sync_all = not (do_hiera or do_site or do_modules or do_puppet_conf)

    # Resolve DPK path
    resolved_dpk = _get_env_path(ENV_DPK_BASE, dpk_path)
    if not resolved_dpk:
        resolved_dpk = Path(DEFAULT_DPK_BASE)

    # Handle both /u01/app/psoft and /u01/app/psoft/dpk
    if resolved_dpk.name != "dpk" and (resolved_dpk / "dpk").exists():
        resolved_dpk = resolved_dpk / "dpk"

    if not resolved_dpk.exists():
        print_error(f"DPK path not found: {resolved_dpk}")
        raise typer.Exit(1)

    # Resolve source path
    resolved_source = _get_source_path(source)
    if not resolved_source.exists():
        print_error(f"Source path not found: {resolved_source}")
        raise typer.Exit(1)

    # Resolve psa_cust_path and psa_kit_path for hiera/puppet.conf generation
    config = get_config()
    resolved_cust = (
        Path(os.environ["PSA_CUST"]) if os.environ.get("PSA_CUST")
        else config.psa_cust_path
    )
    resolved_kit = (
        Path(os.environ["PSA_KIT"]) if os.environ.get("PSA_KIT")
        else config.psa_kit_path
    )

    print_info(f"DPK path: {resolved_dpk}")
    print_info(f"Source: {resolved_source}")
    if resolved_cust:
        print_info(f"PSA Cust: {resolved_cust}")
    if resolved_kit:
        print_info(f"PSA Kit: {resolved_kit}")
    console.print()

    if dry_run:
        console.print("[yellow]Dry run - no changes will be made[/yellow]")
        console.print()

    console.print("[bold]Syncing custom DPK configuration...[/bold]")

    # Deploy hiera.yaml
    if sync_all or do_hiera:
        if not _deploy_hiera_files(resolved_dpk, resolved_cust, resolved_kit, dry_run):
            raise typer.Exit(1)

    # Deploy site.pp
    if sync_all or do_site:
        if not _deploy_site_pp(resolved_dpk, dry_run):
            raise typer.Exit(1)

    # Deploy puppet.conf
    if sync_all or do_puppet_conf:
        if not _deploy_puppet_conf(resolved_dpk, resolved_cust, resolved_kit, dry_run):
            raise typer.Exit(1)

    # Deploy modules
    if sync_all or do_modules:
        if not _deploy_module_files(resolved_dpk, resolved_source, dry_run):
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
