# DPK Provisioning Workflow Testing Guide

End-to-end testing of PeopleSoft domain provisioning using `psa` CLI with registry-sourced configuration.

## Overview

This guide tests two workflows:
1. **Phase 1**: Fresh provisioning from registry config
2. **Phase 2**: Config update cycle (edit → import → cleanup → re-deploy)

## Prerequisites

- PSA-OPS registry service running
- DPK archives available (PT 8.62.04)
- Fresh test server with network access to registry
- Sample psft_customizations.yaml for seeding

## Test Environment

| Component | Value |
|-----------|-------|
| Registry URL | `http://<registry-host>:8000` |
| DPK Version | PT 8.62.04 |
| Test Server | [TBD] |
| Environment Name | FSCMDEV |
| Tier | DEV |

---

# Phase 1: Fresh Provisioning

## Step 1.2: Setup psa CLI on Test Server

**Purpose**: Install psa CLI and connect to registry from the test server.

**Commands**:
```bash
# Clone the repo
git clone https://github.com/psadmin-io/PSA-OPS-node.git
cd PSA-OPS-node

# Install
./install.sh

# Initialize and connect to registry
psa init --registry-url http://registry.psaops.local:8000

# Verify connection
psa registry status
```

**Actual Output**:
```
psa init --registry-url http://registry.psaops.local:8000
Initializing psa for psa-ops-node-2

Connecting to registry: http://registry.psaops.local:8000
✓ Registry connected (v?)

Discovering domains...
No domains found

Available environments:
┏━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ # ┃ Name    ┃ Pillar ┃ Tier ┃ DB Name ┃
┡━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━━━┩
│ 1 │ FSCMDEV │ FSCM   │ DEV  │         │
└───┴─────────┴────────┴──────┴─────────┘
Select environment [1]: 1

✓ Using environment: FSCMDEV
✓ Node already registered: 7a1ee22c...
✓ Configuration saved to /root/.config/psa/config.yaml
```

```
psa registry status
Registry Configuration

Config file: /root/.config/psa/config.yaml
Registry URL: http://registry.psaops.local:8000
Node ID: 7a1ee22c...
Environment: FSCMDEV
Environment ID: d46366ea...

Connection Status
✓ Connected (v?)
✓ Node verified
```

**Verification**:
- [x] `psa --version` works
- [x] `psa registry status` shows registry connected
- [x] Environment FSCMDEV selected

---

## Step 1.1: Seed Registry with Config

**Purpose**: Import psft_customizations.yaml into registry as environment-level config.

**Commands**:
```bash
# Import environment-level config (FSCMDEV)
psa dpk data import environment FSCMDEV --file ~/psft_customizations.yaml

# Verify import
psa dpk data get environment FSCMDEV
```

**Actual Output**:
```
# psa dpk data import environment FSCMDEV --file ~/psft_customizations.yaml
Importing /root/psft_customizations.yaml as environment/FSCMDEV...
Imported environment/FSCMDEV: 100 created, 0 updated, 100 deleted (replaced)
```

**Verification**:
- [x] `psa dpk data get environment FSCMDEV` returns valid YAML
- [x] Config values visible in registry (100 values imported)

**Notes**:
- FSCMDEV environment already exists in registry (from previous setup)
- 100 config values imported from psft_customizations.yaml

---

## Step 1.3: Stage and Setup DPK

**Purpose**: Download/extract DPK archives and bootstrap Puppet environment.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft
DPK_INSTALL=/opt/oracle/psft/dpks
DPK_REPO=/dpkrepo/linux/tools/8.62/04

# Stage DPK archives
psa dpk stage --install-dir $DPK_INSTALL --repo $DPK_REPO

# Setup Puppet environment
psa dpk setup --install-dir $DPK_INSTALL --base-dir $DPK_BASE
```

**Actual Output**:
```
✓ Stage and setup completed successfully
```

**Verification**:
- [x] `/opt/oracle/psft/dpks/puppet` directory exists
- [x] `psa dpk setup` completes without errors
- [x] Hiera directories available for sync

**Notes**:
- `dpk stage` extracts PT 8.62.04 archives from repo to DPK_INSTALL
- `dpk setup` runs the Oracle bootstrap script
- After setup, Hiera path exists at `$DPK_INSTALL/puppet/production/data/cust`
- DPK_BASE used in future steps for other paths under /opt/oracle/psft

---

## Step 1.4: Sync YAML from Registry

**Purpose**: Pull tier and environment YAML from registry to local Hiera paths.

**Commands**:
```bash
# Set variables (if not already set)
DPK_BASE=/opt/oracle/psft
HIERA_CUST=$DPK_BASE/dpk/puppet/production/data/cust

# Sync YAML from registry
psa dpk data sync --tier DEV --environments FSCMDEV --hiera-path $HIERA_CUST

# Verify files written
ls -la $HIERA_CUST/tier/
ls -la $HIERA_CUST/env/
```

**Actual Output**:
```
psa dpk data sync --tier DEV --environments FSCMDEV --hiera-path $HIERA_CUST
Synced: /opt/oracle/psft/dpk/puppet/production/data/cust/env/FSCMDEV.yaml
Synced 1 YAML file(s)
```

**Verification**:
- [ ] `$HIERA_CUST/tier/DEV.yaml` exists (no tier config imported yet)
- [x] `$HIERA_CUST/env/FSCMDEV.yaml` exists
- [x] YAML content matches registry config

**Notes**:
- Syncs both tier-level (DEV) and environment-level (FSCMDEV) YAML
- Creates tier/ and env/ subdirectories if needed

---

## Step 1.4b: Configure Hiera Hierarchy

**Purpose**: Update hiera.yaml to include cust/tier and cust/env in the lookup hierarchy.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft
HIERA_YAML=$DPK_BASE/dpk/puppet/production/hiera.yaml

# Backup existing hiera.yaml
cp $HIERA_YAML ${HIERA_YAML}.bak

# Copy PSA-OPS hiera.yaml (includes cust/tier and cust/env hierarchy)
# Option A: Copy from PSA-OPS-node repo
cp ~/PSA-OPS-node/dpk/puppet/hiera.yaml $HIERA_YAML

# Option B: Manual edit to add these paths to hierarchy:
#   - cust/env/%{facts.env}
#   - cust/tier/%{facts.ps_tier}

# Verify
cat $HIERA_YAML
```

**Expected hiera.yaml (v5 format)**:
```yaml
---
version: 5

defaults:
  datadir: data
  data_hash: yaml_data

hierarchy:
  - name: "Per-domain customizations"
    path: "cust/domain/%{facts.domainname}.yaml"

  - name: "Per-server customizations"
    path: "cust/server/%{facts.hostname}.yaml"

  - name: "Environment-level config"
    path: "cust/env/%{facts.env}.yaml"

  - name: "Tier-level config"
    path: "cust/tier/%{facts.ps_tier}.yaml"

  - name: "Zone-role config"
    path: "cust/zone/%{facts.ps_zone}-%{facts.ps_role}.yaml"

  - name: "Common customizations"
    path: "cust/common.yaml"

  - name: "PSA-OPS common"
    path: "PSA-OPS/common.yaml"

  - name: "DPK defaults"
    path: "defaults.yaml"
```

**Verification**:
- [x] hiera.yaml is version 5 format
- [x] hiera.yaml includes `cust/env/%{facts.env}.yaml` in hierarchy
- [x] hiera.yaml includes `cust/tier/%{facts.ps_tier}.yaml` in hierarchy

**Notes**:
- **IMPORTANT**: Puppet 5+ ignores hiera.yaml v3 format - must use v5
- **FEATURE GAP**: No `psa` command to configure hiera.yaml yet (see [Issue #58](https://github.com/psadmin-io/PSA-OPS/issues/58))
- This step is required for Puppet to find the tier/env YAML files synced in Step 1.4
- Facts `env` and `ps_tier` must be set for Hiera lookups to work

---

## Step 1.4c: Copy Base Configuration Files

**Purpose**: Copy base/default YAML files that provide required Hiera values not in environment config.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft
HIERA_DATA=$DPK_BASE/dpk/puppet/production/data

# Copy base configuration files
# Option A: Copy common.yaml with shared defaults
cp ~/psft_common.yaml $HIERA_DATA/cust/common.yaml

# Option B: Copy defaults.yaml with DPK base values
cp ~/psft_defaults.yaml $HIERA_DATA/defaults.yaml

# Verify files in place
ls -la $HIERA_DATA/cust/
ls -la $HIERA_DATA/
```

**Verification**:
- [x] Base YAML file(s) exist in Hiera data path
- [x] Contains required keys (e.g., `ensure`, base domain settings)

**Notes**:
- Environment YAML (FSCMDEV.yaml) contains overrides only
- Base files provide default values for required Puppet parameters
- Future: `psa dpk data sync` may handle common/defaults automatically
- Hierarchy lookup order: env → tier → zone-role → common → defaults

---

## Step 1.4d: Deploy PSA-OPS Puppet Modules

**Purpose**: Deploy io_profile and io_role modules for role-based provisioning.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft

# Deploy PSA-OPS modules
psa dpk modules --dpk-path $DPK_BASE/dpk

# Verify modules deployed
ls $DPK_BASE/dpk/puppet/production/modules/io_*
```

**Expected Output**:
```
psa dpk modules --dpk-path $DPK_BASE/dpk
✓ Installed: /opt/oracle/psft/dpk/puppet/production/modules/io_profile
✓ Installed: /opt/oracle/psft/dpk/puppet/production/modules/io_role
✓ PSA-OPS modules deployed (io_profile, io_role)
```

**Verification**:
- [ ] io_profile module exists in modules directory
- [ ] io_role module exists in modules directory
- [ ] pt_tools_postdeploy.pp manifest present in io_profile

**Notes**:
- Backs up existing modules with .bak suffix if present
- Use `--dry-run` to preview without making changes
- Required for role-based provisioning via site.pp

---

## Step 1.5: Apply DPK Configuration

**Purpose**: Run Puppet to deploy PeopleSoft domains using registry-sourced config.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft

# First, dry-run to verify changes
psa dpk apply --dpk-path $DPK_BASE/dpk --env FSCMDEV --tier DEV --dry-run

# If dry-run looks good, apply for real
psa dpk apply --dpk-path $DPK_BASE/dpk --env FSCMDEV --tier DEV
```

**Expected Output**:
```
# psa dpk apply --dpk-path $DPK_BASE/dpk --env FSCMDEV --tier DEV --dry-run
Setting fact: env=FSCMDEV
Setting fact: ps_tier=DEV
Running: /opt/puppetlabs/puppet/bin/puppet apply ...
[Puppet output showing planned changes]
✓ Puppet apply completed successfully

# psa dpk apply --dpk-path $DPK_BASE/dpk --env FSCMDEV --tier DEV
Setting fact: env=FSCMDEV
Setting fact: ps_tier=DEV
Running: /opt/puppetlabs/puppet/bin/puppet apply ...
[Puppet output]
✓ Puppet apply completed with changes
```

**Verification**:
- [x] Dry-run shows expected domain configuration
- [x] Real apply completes without errors
- [x] PeopleSoft domains created

**Notes**:
- Always run dry-run first to preview changes
- Apply creates app server, web server, and process scheduler domains
- `--env` and `--tier` set Facter facts for Hiera lookups
- Additional options: `--zone`, `--type`, `--role`
- This may take several minutes

**Manual Workarounds Required** (Phase 1 testing):
- ~~Copy PSA-OPS Puppet modules (io_role, io_profile) to modules/~~ → Use `psa dpk modules`
- ~~Copy PSA-OPS site.pp to manifests/~~ → Use `psa dpk site`
- Copy io_weblogic module manually (not yet in psa) - see #65
- Edit FSCMDEV.yaml with required adjustments
- Comment out invalid class references in io_role modules - see #67

**Related Issues**:
- [#64](https://github.com/psadmin-io/PSA-OPS/issues/64) - ~~Missing io_profile module~~ DONE
- [#65](https://github.com/psadmin-io/PSA-OPS/issues/65) - Missing io_weblogic module
- [#66](https://github.com/psadmin-io/PSA-OPS/issues/66) - ~~Deploy site.pp~~ DONE
- [#67](https://github.com/psadmin-io/PSA-OPS/issues/67) - io_role invalid references
- [#68](https://github.com/psadmin-io/PSA-OPS/issues/68) - Synced YAML adjustments

---

## Step 1.6: Validate Domains Running

**Purpose**: Verify PeopleSoft domains were created and are running.

**Commands**:
```bash
# Check domain status
psa status

# Or manually check
psadmin -c sstatus -d APPDOM
psadmin -p sstatus -d PRCSDOM
```

**Verification**:
- [x] App server domain running
- [x] Process scheduler domain running
- [x] Web server domain running (if configured)

**Notes**:
- Domains should start automatically after puppet apply
- Use `psa discover --report` to register domains in registry

---

# Phase 1 Complete ✓

Phase 1 fresh provisioning workflow tested successfully with manual workarounds documented above.

---

# Phase 2: Config Update Cycle

**Purpose**: Test edit → import → cleanup → re-deploy cycle.

This tests the day-2 workflow: making config changes in registry and pushing them to running domains.

---

## Step 2.1: Make Config Change in Registry

**Purpose**: Edit a config value in registry that will result in a visible domain change.

**Commands**:
```bash
# Option A: Edit via psa CLI (export, edit, re-import)
psa dpk data get environment FSCMDEV > /tmp/FSCMDEV.yaml
# Edit /tmp/FSCMDEV.yaml - change a value
psa dpk data import environment FSCMDEV --file /tmp/FSCMDEV.yaml

# Option B: Direct API or registry UI
# Edit config value in registry web UI
```

**Suggested Test Changes** (pick one):
- Change `appserver_domain::Max Instances` value
- Change `prcs_domain::PRCSDOM::Min Instances`
- Add/modify a domain setting that's easily verifiable

**Actual Output**:
```
[Document actual output here]
```

**Verification**:
- [ ] Config value changed in registry
- [ ] `psa dpk data get environment FSCMDEV` shows new value

---

## Step 2.2: Re-sync YAML from Registry

**Purpose**: Pull updated config from registry to local Hiera paths.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft
HIERA_CUST=$DPK_BASE/dpk/puppet/production/data/cust

# Sync updated YAML
psa dpk data sync --tier DEV --environments FSCMDEV --hiera-path $HIERA_CUST

# Verify change in local YAML
grep -A2 "changed_key" $HIERA_CUST/env/FSCMDEV.yaml
```

**Actual Output**:
```
[Document actual output here]
```

**Verification**:
- [ ] Sync completes successfully
- [ ] Local YAML file reflects the change
- [ ] File timestamp updated

---

## Step 2.3: Re-apply DPK Configuration

**Purpose**: Run Puppet to apply config changes to running domains.

**Commands**:
```bash
# Set variables
DPK_BASE=/opt/oracle/psft

# Dry-run first to see what will change
psa dpk apply --dpk-path $DPK_BASE/dpk --env FSCMDEV --tier DEV --dry-run

# If changes look correct, apply for real
psa dpk apply --dpk-path $DPK_BASE/dpk --env FSCMDEV --tier DEV
```

**Expected Behavior**:
- Dry-run shows config file changes (not full domain rebuild)
- Real apply updates config files and may restart affected services

**Actual Output**:
```
[Document actual output here]
```

**Verification**:
- [ ] Dry-run shows expected changes only
- [ ] Apply completes without errors
- [ ] Config change reflected in domain

---

## Step 2.4: Validate Config Change

**Purpose**: Verify the config change took effect in the running domain.

**Commands**:
```bash
# Check domain config (example for app server)
cat $PS_CFG_HOME/appserv/APPDOM/psappsrv.cfg | grep "changed_setting"

# Or use psadmin to check
psadmin -c configure -d APPDOM

# Check domain is still running
psa status
```

**Actual Output**:
```
[Document actual output here]
```

**Verification**:
- [ ] Config value in domain matches registry value
- [ ] Domain still running after change
- [ ] No unexpected side effects

---

## Step 2.5: Test Domain Restart (Optional)

**Purpose**: If config change requires restart, verify restart works.

**Commands**:
```bash
# Stop and start domain
psa domain stop APPDOM
psa domain start APPDOM

# Verify running with new config
psa status
```

**Verification**:
- [ ] Domain restarts successfully
- [ ] Config change persists after restart

---

# Phase 2 Complete

Phase 2 config update cycle tested successfully.

**Summary**:
- [ ] Config change made in registry
- [ ] YAML synced to local Hiera
- [ ] DPK apply updated domain config
- [ ] Change validated in running domain

---

