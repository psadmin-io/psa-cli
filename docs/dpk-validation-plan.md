# DPK Commands Validation Plan (#45)

## Objective
Validate new DPK commands (`stage`, `setup`, `prereq`, `postcfg`) with real data from fscm-55-node.

## Prerequisites

### 1. Gather fscm-55-node Config
```bash
# SSH to fscm-55-node and gather actual values
ssh fscm-55-node

# Database info
cat $PS_CFG_HOME/appserv/*/psappsrv.cfg | grep -i database
# Or from environment
echo $PS_DB_NAME
echo $PS_DB_SERVICE

# Domain info
ls -la $PS_CFG_HOME/appserv/
ls -la $PS_CFG_HOME/prcs/
ls -la $PS_CFG_HOME/pia/

# Ports
cat $PS_CFG_HOME/appserv/*/psappsrv.cfg | grep -i jolt
cat $PS_CFG_HOME/pia/*/configuration.properties | grep -i port

# Paths
echo $PS_HOME
echo $PS_CFG_HOME
echo $PS_APP_HOME
```

### 2. Locate DPK Archives
```bash
# Find where DPK zips are stored
# Common locations:
ls -la /nfs/dpk/
ls -la /media/dpk/
ls -la /opt/oracle/dpk/

# Note the PT version (e.g., PT 8.62)
```

### 3. Prepare Test Environment
```bash
# Option A: Use a fresh test VM
# Option B: Use isolated test directory on existing node

# Create test workspace
export TEST_WORKSPACE=/tmp/dpk-validation-$(date +%s)
mkdir -p $TEST_WORKSPACE
cd $TEST_WORKSPACE
```

## Validation Tests

### Test 1: Environment Variables

**Goal:** Verify env vars work correctly

```bash
# Set environment variables
export DPK_REPO=/path/to/dpk/zips          # Where DPK archives live
export DPK_INSTALL=$TEST_WORKSPACE/install  # Staging area
export DPK_BASE=$TEST_WORKSPACE/psft        # Install location

# Verify they're set
env | grep DPK_

# Test that commands pick them up
psa dpk stage  # Should use DPK_REPO and DPK_INSTALL without flags
```

**Expected:**
- Commands use env vars when flags not provided
- Clear error if vars not set and flags not provided

**Actual:**
```
# Record results here
```

---

### Test 2: `psa dpk stage` Command

**Goal:** Stage DPK files correctly

#### Test 2.1: Stage with Explicit Paths
```bash
psa dpk stage \
  --repo /path/to/dpk/archives \
  --install-dir $TEST_WORKSPACE/install1
```

**Verify:**
- [ ] All zip files copied to install dir
- [ ] First zip detected correctly (check pattern: *_1of*.zip or *-01.zip)
- [ ] Only first zip extracted
- [ ] `setup/psft-dpk-setup.sh` exists
- [ ] Other zips still zipped

```bash
# Check results
ls -la $TEST_WORKSPACE/install1/*.zip
ls -la $TEST_WORKSPACE/install1/setup/
file $TEST_WORKSPACE/install1/setup/psft-dpk-setup.sh
```

#### Test 2.2: Stage with Env Vars
```bash
export DPK_REPO=/path/to/dpk/archives
export DPK_INSTALL=$TEST_WORKSPACE/install2

psa dpk stage  # No flags
```

**Verify:**
- [ ] Uses env vars correctly
- [ ] Same results as Test 2.1

#### Test 2.3: Dry Run
```bash
psa dpk stage --dry-run \
  --repo /path/to/dpk/archives \
  --install-dir $TEST_WORKSPACE/install3
```

**Verify:**
- [ ] Shows what would be done
- [ ] No actual files copied
- [ ] No directories created

#### Test 2.4: Error Cases
```bash
# Missing repo
psa dpk stage --install-dir /tmp/test
# Expected: Error message about missing DPK_REPO

# Nonexistent repo
psa dpk stage --repo /nonexistent --install-dir /tmp/test
# Expected: Error about repo not found

# No zip files in repo
mkdir /tmp/empty-repo
psa dpk stage --repo /tmp/empty-repo --install-dir /tmp/test
# Expected: Error about no zip files

# Permission denied
psa dpk stage --repo /path/to/dpk --install-dir /root/forbidden
# Expected: Permission denied error
```

**Actual Results:**
```
# Record errors and messages
```

---

### Test 3: `psa dpk response-template` Command

**Goal:** Generate valid response file template

```bash
# Generate template
psa dpk response-template --output $TEST_WORKSPACE/response.txt

# Verify template created
cat $TEST_WORKSPACE/response.txt

# Generate for different platform
psa dpk response-template --platform MSSQL --output $TEST_WORKSPACE/response_mssql.txt
```

**Verify:**
- [ ] Template contains all required fields
- [ ] Platform option works (ORACLE, MSSQL, DB2ODBC)
- [ ] Placeholders clearly marked (`<CHANGE_ME>`)
- [ ] Comments helpful

---

### Test 4: Edit Response File with Real Values

**Goal:** Create working response file from fscm-55-node data

```bash
# Copy template
cp $TEST_WORKSPACE/response.txt $TEST_WORKSPACE/fscm55_response.txt

# Edit with real values (use values from Prerequisites step 1)
nano $TEST_WORKSPACE/fscm55_response.txt
```

**Fill in these values from fscm-55-node:**
```properties
env_type=midtier
psft_base_dir="$TEST_WORKSPACE/psft"  # Use test path, not production
user_home_dir="$HOME/psadm"

# Database (from fscm-55-node)
db_platform=ORACLE
db_name=<actual_db_name>
db_service_name=<actual_service_name>
db_host=<actual_db_host>
db_port=<actual_port>
db_is_unicode=true

# Credentials (use test passwords, NOT production!)
connect_id=people
connect_pwd=<test_password>
opr_id=PS
opr_pwd=<test_password>

# WebLogic
weblogic_admin_pwd=<test_password>

# Web profile
webprofile_user_id=PTWEBSERVER
webprofile_user_pwd=<test_password>

# Domain connection
domain_conn_pwd=<test_password>

# Integration Gateway
gw_user_id=administrator
gw_user_pwd=<test_password>
gw_keystore_pwd=<test_password>
```

**Validate response file syntax:**
```bash
# Check for common issues
grep '<CHANGE_ME>' $TEST_WORKSPACE/fscm55_response.txt
# Should return nothing if all placeholders replaced

# Check for required fields
for field in env_type psft_base_dir db_name connect_pwd; do
  grep "^$field=" $TEST_WORKSPACE/fscm55_response.txt || echo "Missing: $field"
done
```

---

### Test 5: `psa dpk setup` - Dry Run

**Goal:** Verify setup command builds correct arguments

```bash
export DPK_INSTALL=$TEST_WORKSPACE/install1

# Test with explicit args
psa dpk setup --dry-run \
  --base-dir $TEST_WORKSPACE/psft \
  --env-type midtier \
  --domain-type all

# Test with response file
psa dpk setup --dry-run \
  --response-file $TEST_WORKSPACE/fscm55_response.txt

# Test deploy-only option
psa dpk setup --dry-run \
  --deploy-only \
  --deploy-type tools_home \
  --base-dir $TEST_WORKSPACE/psft
```

**Verify:**
- [ ] Command shows correct psft-dpk-setup.sh path
- [ ] Arguments properly formatted
- [ ] Response file path correct
- [ ] No execution in dry-run mode

**Check output matches Oracle docs:**
```
Expected: ./psft-dpk-setup.sh --env_type midtier --domain_type all
Expected: ./psft-dpk-setup.sh --silent --response_file=/path/to/file
Expected: ./psft-dpk-setup.sh --env_type midtier --deploy_only --deploy_type tools_home
```

---

### Test 6: `psa dpk setup` - Interactive Mode (Limited)

**Goal:** Test interactive mode startup (don't complete full install)

⚠️ **WARNING:** This will start actual DPK installation. Be prepared to Ctrl+C.

```bash
export DPK_INSTALL=$TEST_WORKSPACE/install1

# Start interactive setup
psa dpk setup \
  --base-dir $TEST_WORKSPACE/psft \
  --env-type midtier

# Should prompt for:
# - Base directory confirmation
# - Database platform
# - Database name
# - Etc.

# Press Ctrl+C after verifying prompts appear
```

**Verify:**
- [ ] Script starts correctly
- [ ] Prompts appear as expected
- [ ] Can Ctrl+C to exit cleanly

**Actual:**
```
# Record first few prompts seen
```

---

### Test 7: `psa dpk setup` - Silent Mode (Full Test)

**Goal:** Complete DPK installation with response file

⚠️ **WARNING:** This is a full installation and will take 1-2 hours.

#### Test 7.1: PS_HOME Only (Faster Test)

```bash
# Create minimal response file for PS_HOME only
cat > $TEST_WORKSPACE/response_pshome.txt <<'EOF'
env_type=midtier
psft_base_dir="$TEST_WORKSPACE/psft"
deploy_only=true
deploy_type=tools_home
EOF

# Run setup
export DPK_INSTALL=$TEST_WORKSPACE/install1

psa dpk setup \
  --response-file $TEST_WORKSPACE/response_pshome.txt \
  --log-file $TEST_WORKSPACE/setup_pshome.log

# Monitor progress
tail -f $TEST_WORKSPACE/setup_pshome.log
```

**Expected Duration:** ~30-45 minutes

**Verify:**
- [ ] Setup completes successfully
- [ ] PS_HOME created at $TEST_WORKSPACE/psft/pt/ps_home8.62.xx
- [ ] Puppet installed at $TEST_WORKSPACE/psft/psft_puppet_agent
- [ ] Log file shows success
- [ ] No errors in log

```bash
# Check installation
ls -la $TEST_WORKSPACE/psft/pt/
ls -la $TEST_WORKSPACE/psft/psft_puppet_agent/

# Check for puppet
$TEST_WORKSPACE/psft/psft_puppet_agent/puppet/bin/puppet --version
```

#### Test 7.2: Full Mid-Tier (Complete Test)

**Only run if Test 7.1 succeeded**

```bash
# Use full response file from Test 4
export DPK_INSTALL=$TEST_WORKSPACE/install1

psa dpk setup \
  --response-file $TEST_WORKSPACE/fscm55_response.txt \
  --log-file $TEST_WORKSPACE/setup_full.log \
  --debug  # Include debug for troubleshooting

# Monitor
tail -f $TEST_WORKSPACE/setup_full.log
```

**Expected Duration:** ~1.5-2 hours

**Verify:**
- [ ] Setup completes successfully
- [ ] PS_HOME created
- [ ] Domains created (appserver, prcs, pia)
- [ ] Services configured
- [ ] No critical errors in log

```bash
# Check domains
ls -la $PS_CFG_HOME/appserv/
ls -la $PS_CFG_HOME/prcs/
ls -la $PS_CFG_HOME/pia/

# Check if domains start
psadmin -c start -d <domain_name>
```

**Log Analysis:**
```bash
# Check for errors
grep -i error $TEST_WORKSPACE/setup_full.log | grep -v "0 errors"
grep -i fail $TEST_WORKSPACE/setup_full.log
grep "\[FAILED\]" $TEST_WORKSPACE/setup_full.log

# Check success messages
grep "\[  OK  \]" $TEST_WORKSPACE/setup_full.log | tail -20
grep "Setup Process Ended" $TEST_WORKSPACE/setup_full.log
```

---

### Test 8: `psa dpk prereq` Command

**Goal:** Verify prereq command for non-root deployments

⚠️ **Must run as root**

```bash
# Dry run
sudo psa dpk prereq --dry-run --install-dir $TEST_WORKSPACE/install1

# Actual run
sudo psa dpk prereq --install-dir $TEST_WORKSPACE/install1
```

**Verify:**
- [ ] Warns if not run as root
- [ ] Checks Oracle central inventory
- [ ] Completes successfully
- [ ] Creates necessary files/permissions

**Check results:**
```bash
# Check for oraInst.loc
cat /etc/oraInst.loc

# Check oinstall group
getent group oinstall
```

---

### Test 9: `psa dpk postcfg` Command

**Goal:** Verify post-config command

⚠️ **Must run as root, after non-root setup**

```bash
# Dry run
sudo psa dpk postcfg --dry-run \
  --install-dir $TEST_WORKSPACE/install1 \
  --base-dir $TEST_WORKSPACE/psft

# Actual run
sudo psa dpk postcfg \
  --install-dir $TEST_WORKSPACE/install1 \
  --base-dir $TEST_WORKSPACE/psft
```

**Verify:**
- [ ] Completes Oracle DB client setup
- [ ] No errors
- [ ] Appropriate permissions set

---

### Test 10: `psa dpk status` Command

**Goal:** Verify status detection after installation

```bash
# Check status
psa dpk status

# With DPK_BASE set
export DPK_BASE=$TEST_WORKSPACE/psft
psa dpk status
```

**Verify:**
- [ ] Detects Puppet installation
- [ ] Finds DPK directory
- [ ] Shows hiera.yaml location
- [ ] Shows site.pp location
- [ ] Overall status "ready for provisioning"

---

### Test 11: `psa dpk apply` Command

**Goal:** Verify puppet apply works

```bash
# Dry run (noop)
psa dpk apply --noop --dpk-path $TEST_WORKSPACE/psft

# With debug
psa dpk apply --noop --debug --dpk-path $TEST_WORKSPACE/psft

# Actual apply (if needed)
psa dpk apply --dpk-path $TEST_WORKSPACE/psft
```

**Verify:**
- [ ] Finds puppet binary
- [ ] Locates manifests
- [ ] Runs without errors in noop mode
- [ ] Shows what would change

---

### Test 12: Deprecated `bootstrap` Command

**Goal:** Verify deprecation warning works

```bash
# Try old bootstrap command
psa dpk bootstrap /path/to/single.zip --dry-run
```

**Verify:**
- [ ] Shows deprecation warning
- [ ] Suggests new workflow
- [ ] Still executes (for backwards compat)
- [ ] Warning is clear and helpful

---

## Edge Cases & Error Handling

### Edge Case 1: Multiple Zip Patterns
```bash
# Test with different naming conventions
# Oracle: PT862_1of5.zip, PT862_2of5.zip
# MOS: V123456-01.zip, V123456-02.zip

# Create test repo with different patterns
mkdir /tmp/dpk-patterns
touch /tmp/dpk-patterns/PT862_{1..5}of5.zip
psa dpk stage --repo /tmp/dpk-patterns --install-dir /tmp/test1

mkdir /tmp/dpk-patterns2
touch /tmp/dpk-patterns2/V123456-{01..05}.zip
psa dpk stage --repo /tmp/dpk-patterns2 --install-dir /tmp/test2

mkdir /tmp/dpk-patterns3
touch /tmp/dpk-patterns3/PTDPK_{1..3}.zip
psa dpk stage --repo /tmp/dpk-patterns3 --install-dir /tmp/test3
```

**Verify:**
- [ ] Detects correct "first" file for each pattern
- [ ] Handles all three naming conventions

### Edge Case 2: Partial Staging
```bash
# Stage files
psa dpk stage --repo /path/to/dpk --install-dir /tmp/staged

# Run again (files already exist)
psa dpk stage --repo /path/to/dpk --install-dir /tmp/staged
```

**Verify:**
- [ ] Skips already-copied files
- [ ] Reports "exists" message
- [ ] Doesn't re-extract first zip
- [ ] Completes successfully

### Edge Case 3: Missing Fields in Response File
```bash
# Create incomplete response file
cat > /tmp/bad_response.txt <<EOF
env_type=midtier
# Missing psft_base_dir
db_platform=ORACLE
EOF

psa dpk setup --response-file /tmp/bad_response.txt
```

**Verify:**
- [ ] Oracle script validates and prompts
- [ ] OR shows clear error about missing field

### Edge Case 4: Invalid Paths
```bash
# Setup with nonexistent install dir
psa dpk setup --install-dir /nonexistent --base-dir /tmp/test

# Prereq with bad path
psa dpk prereq --install-dir /does/not/exist
```

**Verify:**
- [ ] Clear error messages
- [ ] No crashes
- [ ] Suggests running `psa dpk stage` first

---

## Success Criteria

### Must Pass
- [x] All commands execute without crashes
- [x] Environment variables work correctly
- [x] Response file template generates correctly
- [x] Dry-run mode works for all commands
- [x] Error messages are clear and helpful
- [x] At least one successful PS_HOME installation (Test 7.1)

### Should Pass
- [ ] Full mid-tier installation completes (Test 7.2)
- [ ] All three zip patterns detected correctly
- [ ] prereq/postcfg work for non-root flow
- [ ] puppet apply works after setup

### Nice to Have
- [ ] Interactive mode tested with real prompts
- [ ] Multiple installations in parallel
- [ ] Cleanup and re-run scenarios

---

## Documentation Updates Needed

Based on validation results:
- [ ] Update README with new command examples
- [ ] Add troubleshooting section for common errors
- [ ] Document environment variable usage
- [ ] Add example response files for different scenarios
- [ ] Update #45 issue with validation results

---

## Rollback Plan

If validation fails:
1. Document the failure mode
2. Create bug fix plan
3. Keep deprecated `bootstrap` command working
4. Don't merge to main until validation passes

---

## Timeline Estimate

| Phase | Duration | Notes |
|-------|----------|-------|
| Prerequisites (gather data) | 30 min | One-time setup |
| Tests 1-6 (validation) | 1 hour | Quick tests |
| Test 7.1 (PS_HOME only) | 45 min | First real install |
| Test 7.2 (Full mid-tier) | 2 hours | Complete install |
| Tests 8-12 (remaining) | 30 min | Quick validation |
| Edge cases | 30 min | Error handling |
| Documentation | 1 hour | Update docs |
| **Total** | **~6 hours** | Spread over 1-2 days |

---

## Notes & Observations

```
# Use this section to record findings during validation

## Working Well:
-

## Issues Found:
-

## Surprises:
-

## Performance:
-

## Questions:
-
```
