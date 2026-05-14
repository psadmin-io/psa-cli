# Changelog

All notable changes to psa-cli are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `psa ops register [DOMAIN...]` — push locally-discovered domains to PSA-OPS. Idempotent (server upserts). Supports `--yes`, `--quiet`, `--verbose`, `--json`, and an optional positional list of domain names for subset registration.
- `psa ops setup` now auto-registers discovered domains as a final step. Use `--skip-domains` to register the node only.

### Changed
- "Domain not found in PSA-OPS" errors (`psa domain compare --ops`, `psa ops set-env`, `psa ops compare`) now point users at `psa ops register`.
- Moved `_apply_verbosity` from `psa.commands.domain` to `psa.core.output.apply_verbosity` for shared use across command modules.

## [0.3.0] — 2026-05-12

**First public release.** psa-cli is now open source under the MIT license. This release collapses the un-tagged 0.2.1 through 0.2.5 development work into the first public cut.

> :warning: **Pre-1.0 / beta.** Not yet recommended for production. The CLI surface, config schema, and command behavior may change before 1.0.

### Highlights

- **Domain lifecycle** — `psa domain list / status / start / stop / restart / bounce / compare` with Rich-rendered output, JSON mode, quiet/verbose flags, and `--force` confirmation skips.
- **DPK workflow** — end-to-end PeopleSoft DPK provisioning: `psa dpk stage → setup → init → sync → apply → cleanup`, including a 3-tier Hiera layout, `dpk module install` for custom Puppet modules, `dpk facts` for site facts, and `dpk lookup` for hiera key resolution.
- **`psa dpk apply --summary`** — filtered, readable Puppet apply output with surfaced errors, exit-code mapping, and ANSI handling.
- **Discovery** — `psa discover` finds local PeopleSoft domains and can report results to a configured API.
- **Configuration** — `psa config setup` (interactive + `--yes` non-interactive), `psa config show`, `psa config set` for individual keys, with auto-detection of `PS_*` and `DPK_*` paths.
- **Resilient file operations** — `SudoFileOps` abstraction transparently cascades to `sudo` when the runtime user lacks write permission, with timeout-driven diagnostics for missing passwordless sudo.

### Added since v0.2.0

#### Domain
- `psa domain compare` replaces `psa domain drift`; archive picker, archive age display, raw-config diff that handles `%PS_SERVDIR%` vars
- Global `-q/--quiet` / `-v/--verbose` flags; Rich spinners
- `--force/-f` flag (renamed from `--yes/-y`) on destructive operations
- `psa domain status --json` with full process detail
- Web tier renamed `pia` → `web`; status/start/stop route through `psadmin -w` for PT 8.62
- Graceful already-stopped / already-purged handling

#### DPK
- `psa dpk` command group consolidates DPK provisioning
- `psa dpk module install <org/repo>` with `--branch`, `--dry-run`, `--as <name>`
- `psa dpk facts` (writes to `/etc/`, not the DPK install tree)
- `psa dpk init` auto-creates config, generates `hiera.yaml` (eyaml backend), 3-tier hiera layout
- `psa dpk lookup` for hiera key resolution
- `psa dpk apply --summary` mode + puppet error surfacing + stderr scanning + Rich bypass for raw streams
- `psa dpk apply` auto-sudo to root unless already root or `runtime_user`
- `psa dpk sync` with `SudoFileOps` permission fallback
- `psa dpk status --json` + manifest parsing
- `psa dpk cleanup --domains-only` for scoped domain+service teardown
- `psa dpk stage --version` and `--dry-run` fix
- Split `DPK_BASE` vs `DPK_HOME` with `--dpk-cust-home` flag
- EL 9+ ncurses prereq: per-lib symlink fallback
- OL8/RHEL8+ libnsl in DPK prereq checks
- DPK repo commands: `init`, `status`, `list`

#### Config
- `psa config set` for individual config keys (`ps_cfg_home`, `ps_base`, `ps_home`, etc.)
- `psa config show` groups DPK paths, uppercases path labels
- `DPK_CUST_HOME` foundation (renamed from `PSA_CUST`)

#### Quality / internal
- Minimum Python bumped to 3.9
- `SudoFileOps` centralized file operations
- Resilient domain discovery (skips permission errors, scopes by type)
- Test fixes: verbosity reset, tmadmin process-table parsing, "Started" prcs pattern
- Demo-lab regression fixes: status parser, PIA paths, empty errors, PS path auto-detect

### Removed

- `psa cache` and `psa secrets` (stub commands that were never wired into the CLI)
- `psa domain drift` (replaced by `psa domain compare`)
- `start/stopPIA.sh` shim (now routes through `psadmin -w`)
- `io_base` config key

### Known limitations

- **Encrypted password leak in JSON** — `psa domain --json` includes raw config content that contains encrypted password fields (`ConnectPswd`, `OprPswd`, etc). Values are encrypted, not cleartext, but should not appear in piped output. Tracked as issue #23, fix planned for 0.4.
- Tested against **PeopleTools 8.62**; older versions may work but are unverified.
- No PyPI release yet — install from the GitHub release wheel or from source.

### Compatibility

- Python 3.9, 3.10, 3.11, 3.12
- Linux (Oracle Linux 8/9, RHEL 8/9 covered; other distros likely fine)
- PeopleTools 8.62

[0.3.0]: https://github.com/psadmin-io/psa-cli/releases/tag/v0.3.0
