# `psa dpk`

PeopleSoft DPK provisioning end-to-end: stage archives, install prereqs, generate hiera, apply Puppet.

## Workflow

```
stage → setup → init → sync → apply → (cleanup)
```

For a guided walkthrough see [DPK provisioning workflow](../dpk/provisioning-workflow.md).

## Subcommands

| Command | Description |
|---|---|
| `psa dpk stage` | Unpack DPK archives into the install dir |
| `psa dpk setup` | Run OS prereqs + Puppet install |
| `psa dpk init` | Generate `hiera.yaml`, customer dir, environment.conf |
| `psa dpk sync` | Pull YAMLs (from API or source) into the customer dir |
| `psa dpk apply` | Run `puppet apply` with the configured manifests |
| `psa dpk lookup <key>` | Resolve a hiera key |
| `psa dpk facts` | Write site facts to `/etc/facter/facts.d/` |
| `psa dpk module install <org/repo>` | Install a custom Puppet module |
| `psa dpk status` | Show install state and manifest details |
| `psa dpk cleanup` | Tear down DPK install (with `--domains-only` for scoped removal) |
| `psa dpk repo init / status / list` | Manage DPK source repositories |

## `dpk apply --summary`

By default `puppet apply` floods the terminal. `--summary` mode:

- Suppresses informational Notice lines using an allow-list
- Strips ANSI escapes before prefix matching
- Surfaces Puppet errors with exit-code mapping and diagnostics
- Bypasses Rich for raw stream output so log timing is preserved

```bash
psa dpk apply --summary
```

## Permissions

`psa dpk apply` auto-escalates to `root` unless already running as root or as the configured `runtime_user`.

`psa dpk sync` writes through `SudoFileOps` and transparently cascades to `sudo bash -c` when the runtime user can't write to the target.

If a sudo write hangs more than 30s, psa assumes a password prompt and exits with a hint about configuring passwordless sudo.

## Environment variables

| Variable | Purpose |
|---|---|
| `DPK_BASE`       | DPK install parent dir (used by `setup`, `cleanup`, `status`) |
| `DPK_HOME`       | DPK install dir, conventionally `$DPK_BASE/dpk` (used by `sync`, `apply`, `init`) |
| `DPK_CUST_HOME`  | Customer customizations dir (used by `init`, `module install`, `sync`) |

These can also be set in `~/.config/psa/config.yaml` via `psa config set`.

## Examples

```bash
# Stage a specific PeopleTools version
psa dpk stage --version 8.62.04

# Initialize hiera + customer dir
psa dpk init

# Install a custom Puppet module
psa dpk module install psadmin-io/io_role --branch develop

# Resolve a hiera key
psa dpk lookup ps_app_home

# Status with JSON manifest details
psa dpk status --json

# Targeted cleanup (just one domain, all of its types)
psa dpk cleanup --domains-only --domain APPDOM
```
