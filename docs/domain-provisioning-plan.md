# Domain Provisioning Plan - Issue #38

Deploy domains via PSA and DPK based on registry config.

---

## Current State

**Available:**
- Registry stores: environments, nodes, domains, config snapshots (versioned)
- `psa discover` scans nodes, pushes to registry
- Rundeck can SSH to nodes, execute commands as psadm2
- Puppet/DPK modules exist: `io_role::io_tools_appserver`, `io_tools_prcs`, `io_tools_pia`
- Raw config files stored: `psappsrv.cfg`, `psprcs.cfg`, `configuration.properties`

**Missing:**
- Config-to-DPK YAML generator
- Provisioning orchestration (Rundeck jobs or API endpoints)
- "Desired state" config definition separate from scanned state

---

## Option A: Direct psadmin Wrapper (Quickest Win)

**Approach:** Rundeck jobs call psadmin commands directly, config values passed as job options.

```
Rundeck Job: Create App Domain
  - Node filter: target server
  - Options: domain_name, db_name, db_type, jolt_port
  - Script:
    psadmin -c create -d ${domain_name} ...
    psadmin -c configure -d ${domain_name} -t appserver ...
    psadmin -c start -d ${domain_name}
```

**Pros:**
- Works immediately, no new code
- Familiar to PS admins
- Easy to debug

**Cons:**
- Manual option entry (no registry integration)
- No idempotency - reruns may fail or duplicate
- Config drift not tracked

**Effort:** 1-2 days

---

## Option B: Registry-Driven Script Generation

**Approach:** API endpoint generates shell script from registry domain config, Rundeck executes.

```
Flow:
1. UI: "Deploy Domain X to Node Y"
2. API: GET /api/v1/domains/{id}/deploy-script
   Returns: shell script with psadmin commands
3. Rundeck: Execute script on target node
```

**New Components:**
- `POST /api/v1/domains/{id}/generate-script` - returns deploy script
- Rundeck job that fetches + executes script

**Pros:**
- Config comes from registry (source of truth)
- Script can be previewed/audited before run
- Low barrier - just shell commands

**Cons:**
- Still imperative, not idempotent
- No convergence checking
- Script maintenance overhead

**Effort:** 3-5 days

---

## Option C: DPK YAML Generation + Puppet Apply (Recommended)

**Approach:** Generate `psft_customizations.yaml` from registry config, puppet apply via Rundeck.

```
Flow:
1. UI: "Provision Domain" button
2. API: POST /api/v1/domains/{id}/provision
   - Generates psft_customizations.yaml from config
   - Triggers Rundeck job with YAML content
3. Rundeck:
   - Writes YAML to node
   - Runs puppet apply
4. Result: Domain converged to desired state
```

**New Components:**
- Config-to-YAML converter (Python, uses stored parsed_content)
- `/api/v1/domains/{id}/generate-yaml` endpoint
- Rundeck job: "Apply Domain Config"

**Sample YAML Output:**
```yaml
# Generated from Registry domain abc123
---
appserver_domain_list:
  HRDEV:
    db_settings:
      db_name: HRDEV
      db_type: ORACLE
    config_settings:
      Domain Settings/Domain ID: HRDEV
      JOLT Listener/Port: 9033
      JOLT Listener/Address: //myserver.example.com:9033
```

**Pros:**
- Idempotent - rerun safely
- Leverages existing DPK infrastructure
- Config versioning built in
- Can diff YAML before applying

**Cons:**
- Need DPK properly configured on nodes
- More complex initial setup
- Puppet failures can be opaque

**Effort:** 1-2 weeks

---

## Option D: Hybrid - Registry API + psa CLI (Best Balance)

**Approach:** Extend `psa` CLI with `provision` command that pulls config from registry.

```
Flow:
1. Registry defines desired domain config
2. Rundeck runs: psa domain provision --from-registry --domain-id {uuid}
3. psa CLI:
   - Fetches config from registry API
   - Generates local psft_customizations.yaml
   - Calls puppet apply OR psadmin commands
4. Reports result back to registry
```

**New Components:**
- `psa domain provision` command
- `psa domain diff` - compare local vs registry desired state
- Registry "desired_config" field (separate from scanned config_snapshot)

**Pros:**
- Single tool on node handles orchestration
- Can work offline (cache config)
- Flexible backend (puppet or psadmin)
- Natural extension of existing `psa` tool

**Cons:**
- More development on node tooling
- Need to handle puppet vs non-puppet environments

**Effort:** 2-3 weeks

---

## Full Bootstrapping Scope

### DPK Handles (via `psft_customizations.yaml`)
1. **Node Prep** - OS packages, users, directories
2. **PS_HOME** - PeopleTools installation
3. **PS_APP_HOME** - Application installation
4. **PS_CFG_HOME** - Configuration home setup
5. **Domains** - App, Prcs, PIA creation/config

### Post-Deploy (PSA-OPS orchestration)
6. **Registry sync** - Push discovered config back to registry
7. **Rundeck registration** - Add node to Rundeck inventory
8. **Health validation** - Run health check job, verify domains started
9. **Monitoring setup** - Register with monitoring system (future)

Our job: generate correct `psft_customizations.yaml` + orchestrate post-deploy steps via Rundeck.

---

## Recommended Phased Approach

### Phase 1: Quick Win (Option B - Script Generation)
1. Add `/api/v1/domains/{id}/deploy-script` endpoint
2. Create Rundeck job template
3. Manual trigger from Rundeck UI

### Phase 2: DPK Integration (Option C partial)
1. Add YAML generator for common domain types
2. Test puppet apply flow manually
3. Integrate into Rundeck

### Phase 3: Full Automation (Option D)
1. Add `psa domain provision` command
2. Add "desired state" to registry model
3. UI for provisioning workflow
4. Drift detection (scanned vs desired)

---

## Registry Schema Additions

For proper provisioning, consider adding:

```python
class Domain:
    # Existing
    config_snapshot: JSONB      # scanned/actual state

    # New
    desired_config: JSONB       # target state for provisioning
    provision_status: str       # pending, provisioning, synced, drifted
    last_provisioned: DateTime
```

---

## Quick Start: Minimal Rundeck Job

For immediate use without code changes:

```yaml
- name: Deploy App Domain (Manual)
  description: Create/configure appserver domain via psadmin
  group: Provisioning
  nodefilters:
    filter: '${option.target_node}'
  options:
    - name: target_node
      required: true
    - name: domain_name
      required: true
    - name: db_name
      required: true
    - name: jolt_port
      default: '9000'
  sequence:
    commands:
    - description: Create domain
      exec: |
        sudo -u psadm2 bash -c '
        source /home/psadm2/psft/pt/ps_home8xx/psconfig.sh
        psadmin -c create -d @option.domain_name@ -t new
        '
    - description: Configure and boot
      exec: |
        sudo -u psadm2 bash -c '
        cd /home/psadm2/psft/pt/ps_cfg_home
        # Edit psappsrv.cfg with sed or puppet
        psadmin -c configure -d @option.domain_name@
        psadmin -c boot -d @option.domain_name@
        '
```

---

## Decisions

1. **DPK availability:** Yes - all nodes have DPK installed
2. **Config source:** Support both - clone existing OR manual entry
3. **Approval workflow:** No - direct deploy
4. **Credentials:** DPK eyaml on nodes; upstream source TBD
5. **Scope:** Full bootstrapping (PS_HOME, PS_CFG_HOME, not just domains)
6. **Rollback:** Future consideration - not in initial scope

---

## Remaining Questions

1. **Credential upstream source** - DPK eyaml confirmed for node-level storage, but where do creds originate?
   - Manual entry in UI during provisioning? (simplest for v1)
   - Stored encrypted in registry, exported to eyaml?

---

## Future Considerations

- **Vault integration** - HashiCorp Vault as credential source of truth, inject into eyaml at deploy time
- **Rollback** - Keep previous YAML versions, ability to redeploy prior config
- **Drift detection** - Compare deployed state vs registry desired state
- **Scheduled deployments** - Deploy during maintenance windows
- **Multi-node orchestration** - Coordinated deploys across app server pools
