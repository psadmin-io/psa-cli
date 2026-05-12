# DPK provisioning workflow

End-to-end PeopleSoft DPK provisioning with `psa`. This guide walks through:

1. Staging DPK archives
2. OS prereqs and Puppet install
3. Hiera + customer dir initialization
4. Pulling configuration (from an API or local source)
5. Running `puppet apply`
6. Cleanup / teardown

## Prerequisites

- A Linux host (Oracle Linux 8/9 or RHEL 8/9 recommended)
- DPK archives for your PeopleTools version (e.g. PT 8.62.04 `.zip` files)
- Passwordless `sudo` for the runtime user (recommended)
- `psa-cli` installed — see [Install](../install.md)

## 1. Stage the DPK

`psa dpk stage` unpacks DPK archives into the install directory.

```bash
# Stage a specific version
psa dpk stage --version 8.62.04

# Or specify the source directory directly
psa dpk stage --source /path/to/dpk/archives

# Dry run — see what would happen, don't extract
psa dpk stage --dry-run
```

The first stage saves `dpk_repo_path` and `dpk_base` into `~/.config/psa/config.yaml` so later commands don't need the flags.

## 2. Install OS prereqs

```bash
# Check prereqs
psa dpk setup --prereq

# Install missing prereqs (uses dnf/yum under the hood)
psa dpk setup --prereq --fix
```

`--prereq` checks for required system libraries (`libncursesw`, `libaio`, `libnsl` on OL8+). On EL 9+, ncurses has a per-lib symlink fallback for compatibility.

Run the full setup (prereqs + Puppet install + DPK relocation):

```bash
psa dpk setup
```

## 3. Initialize the customer dir

`psa dpk init` generates `hiera.yaml`, an empty customer directory tree, and `environment.conf`:

```bash
psa dpk init
```

The generated `hiera.yaml` uses a 3-tier layout:

```
common.yaml          # site-wide defaults
<tier>.yaml          # DEV / TEST / PROD
<environment>.yaml   # per-environment overrides
```

The eyaml backend is enabled for encrypted values. Hiera data lives in `$DPK_CUST_HOME/data/`.

If `~/.config/psa/config.yaml` doesn't exist yet, `init` will create one.

## 4. Sync configuration

`psa dpk sync` pulls hiera YAMLs from your configured source into `$DPK_CUST_HOME`.

```bash
# Sync from configured source
psa dpk sync

# Specify tier / environments explicitly
psa dpk sync --tier DEV --environments FSCMDEV,HCMDEV

# Specify hiera path override
psa dpk sync --hiera-path data/custom
```

When the runtime user can't write to the target, sync transparently cascades through `sudo bash -c`. A 30-second timeout on the sudo write surfaces a hint to configure passwordless sudo.

## 5. Apply the manifest

`psa dpk apply` runs `puppet apply` against the DPK manifests.

```bash
# Full apply (defaults to root via sudo when needed)
psa dpk apply

# Filtered, readable output
psa dpk apply --summary
```

`--summary` mode:

- Suppresses informational `Notice:` lines using an allow-list
- Strips ANSI escapes before prefix matching
- Surfaces Puppet errors with exit-code mapping
- Scans stderr for fatal errors
- Bypasses Rich for raw stream output so timing is preserved

### Looking up resolved hiera values

To check what value Puppet would see for a key without running a full apply:

```bash
psa dpk lookup ps_app_home
psa dpk lookup ps_app_home --tier DEV
```

## 6. Custom Puppet modules

Install a custom module from a GitHub repo:

```bash
psa dpk module install psadmin-io/io_role
psa dpk module install psadmin-io/io_role --branch develop
psa dpk module install psadmin-io/io_role --as my_role  # override target dir name
psa dpk module install psadmin-io/io_role --dry-run
```

Multiple modules at once:

```bash
psa dpk module install psadmin-io/io_role psadmin-io/io_portalwar
```

## 7. Facts

`psa dpk facts` writes site facts to `/etc/facter/facts.d/`:

```bash
psa dpk facts
```

Facts are written to `/etc/`, not the DPK install tree, so they survive DPK relocations.

## 8. Status

```bash
# Quick status
psa dpk status

# JSON, with manifest parsing
psa dpk status --json
```

## 9. Cleanup

```bash
# Full teardown
psa dpk cleanup

# Just one domain (and all of its types: app, prcs, web)
psa dpk cleanup --domains-only --domain APPDOM

# Specific domain + type
psa dpk cleanup --domains-only --domain APPDOM --type app
```

## Iteration loop

Once provisioned, the typical edit-apply loop is:

```bash
# Edit hiera files in $DPK_CUST_HOME/data/
vim $DPK_CUST_HOME/data/common.yaml

# Re-apply
psa dpk apply --summary
```

For destructive config changes, you may want to bounce affected domains:

```bash
psa domain bounce APPDOM
```

## Related

- [`psa dpk` reference](../commands/dpk.md)
- [DPK validation quickstart](validation-quickstart.md)
