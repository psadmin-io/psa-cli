# DPK validation quickstart

A fast track for validating the `psa dpk` command set against an isolated test workspace — useful for testing a new release or a development branch without touching a real environment.

## Prerequisites

- DPK archive `.zip` files for your PeopleTools version
- `psa-cli` installed
- Sufficient disk for an isolated install (~20 GB)

## 1. Locate DPK archives

```bash
find /nfs /media /opt /mnt -name "PT862*.zip" -o -name "V*.zip" 2>/dev/null | head -5
export DPK_REPO=/path/to/dpk/archives
ls -lh $DPK_REPO/*.zip
```

## 2. Set up an isolated workspace

```bash
export DPK_INSTALL=/tmp/dpk-validation-$(date +%s)
export DPK_BASE=$DPK_INSTALL/psft

mkdir -p $DPK_INSTALL
```

Save these for later shells:

```bash
cat <<EOF > /tmp/dpk-env.sh
export DPK_REPO=$DPK_REPO
export DPK_INSTALL=$DPK_INSTALL
export DPK_BASE=$DPK_BASE
EOF
```

## 3. Stage

```bash
psa dpk stage --source $DPK_REPO --install-dir $DPK_INSTALL --version 8.62.04
```

Expected: archives unpack into `$DPK_INSTALL`, `dpk_repo_path` is saved to your psa config.

## 4. Prereqs

```bash
psa dpk setup --prereq
```

Verify the report lists the prereq libraries with `✓` for installed and `✗` for missing. Fix any missing prereqs:

```bash
sudo dnf install -y libnsl libaio ncurses-compat-libs
psa dpk setup --prereq
```

## 5. Setup

```bash
psa dpk setup --dpk-base $DPK_BASE
```

Expected: Puppet is installed under `$DPK_BASE/dpk/puppet/`, DPK is relocated, no fatal errors.

## 6. Init

```bash
psa dpk init --dpk-cust-home $DPK_BASE/dpk-cust
```

Verify:

```bash
ls $DPK_BASE/dpk-cust/data/
cat $DPK_BASE/dpk/puppet/production/hiera.yaml
```

Expected: `data/` contains `common.yaml`, a tier file, and an environment file (or stubs).

## 7. Apply

```bash
psa dpk apply --summary --dpk-home $DPK_BASE/dpk
```

`--summary` mode filters Notice lines but surfaces every error. The command exits non-zero on Puppet errors and prints the matching diagnostic.

## 8. Verify

```bash
psa dpk status --json | jq '.'
```

Expected JSON keys:

- `dpk_base`, `dpk_home`, `dpk_cust_home`
- `manifest` — parsed manifest details
- `puppet_version`
- `domains` — discovered after apply

## 9. Cleanup

```bash
psa dpk cleanup --dpk-base $DPK_BASE --force
rm -rf $DPK_INSTALL
```

## Verifying CLI changes

For testing changes to `psa-cli` itself, install from a feature branch into an isolated venv:

```bash
python3.11 -m venv /tmp/psa-test-venv
source /tmp/psa-test-venv/bin/activate
pip install git+https://github.com/psadmin-io/psa-cli.git@<branch>
psa --version
```

## Related

- [`psa dpk` reference](../commands/dpk.md)
- [Full provisioning workflow](provisioning-workflow.md)
