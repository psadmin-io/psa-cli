# DPK Validation Quick Start

Fast track to validate #45 DPK commands with fscm-55-node config.

## Prerequisites (5 min)

### 1. Locate DPK Archives
```bash
# Find DPK files
find /nfs /media /opt /mnt -name "PT862*.zip" -o -name "V*.zip" 2>/dev/null | head -5

# Note the directory
export DPK_REPO=/path/to/dpk/archives  # Update this!
ls -lh $DPK_REPO/*.zip
```

### 2. Set Up Test Workspace
```bash
# Create isolated test environment
export DPK_INSTALL=/tmp/dpk-validation-$(date +%s)
export DPK_BASE=/tmp/dpk-validation-$(date +%s)/psft

mkdir -p $DPK_INSTALL
echo "DPK_REPO=$DPK_REPO"
echo "DPK_INSTALL=$DPK_INSTALL"
echo "DPK_BASE=$DPK_BASE"

# Save for later
echo "export DPK_REPO=$DPK_REPO" > /tmp/dpk-env.sh
echo "export DPK_INSTALL=$DPK_INSTALL" >> /tmp/dpk-env.sh
echo "export DPK_BASE=$DPK_BASE" >> /tmp/dpk-env.sh
```

## Phase 1: Quick Tests (15 min)

### Test 1: Stage Command
```bash
# Source environment
source /tmp/dpk-env.sh

# Stage files (uses env vars)
psa dpk stage

# Verify
ls -lh $DPK_INSTALL/*.zip
ls -la $DPK_INSTALL/setup/psft-dpk-setup.sh
```

**Expected:**
- ✅ All zips copied
- ✅ First zip extracted
- ✅ `setup/psft-dpk-setup.sh` exists

### Test 2: Response File Template
```bash
# Generate template
psa dpk response-template --output /tmp/response_template.txt

# View it
cat /tmp/response_template.txt
```

**Expected:**
- ✅ Template created with all fields
- ✅ Placeholders marked `<CHANGE_ME>`

### Test 3: Edit Response File
```bash
# Copy pre-filled template from repo
cp /home/kbens/repos/PSA-OPS/dpk_response_fscm55.txt /tmp/dpk_response.txt

# Edit with test values
nano /tmp/dpk_response.txt
```

**MUST CHANGE:**
```properties
# Change these placeholders:
connect_pwd=CHANGE_ME_test123        → YOUR_TEST_PASSWORD
opr_pwd=CHANGE_ME_test123           → YOUR_TEST_PASSWORD
weblogic_admin_pwd=CHANGE_ME_Welcome1 → YOUR_TEST_PASSWORD (8+ chars, 1 upper, 1 lower, 1 num)
webprofile_user_pwd=CHANGE_ME_test123 → YOUR_TEST_PASSWORD
domain_conn_pwd=CHANGE_ME_test123    → YOUR_TEST_PASSWORD
gw_user_pwd=CHANGE_ME_test123       → YOUR_TEST_PASSWORD
gw_keystore_pwd=CHANGE_ME_test123   → YOUR_TEST_PASSWORD

# Update base directory to match your env
psft_base_dir="/tmp/dpk-validation/psft"  → psft_base_dir="$DPK_BASE"

# Optionally change database if not using FSCMQQ
db_name=FSCMQQ        → YOUR_TEST_DB
db_service_name=FSCMQQ → YOUR_TEST_DB
db_host=localhost     → YOUR_DB_HOST
```

**Verify no placeholders remain:**
```bash
grep 'CHANGE_ME' /tmp/dpk_response.txt
# Should return nothing
```

### Test 4: Dry Run
```bash
# Test setup command (doesn't execute)
psa dpk setup --dry-run --response-file /tmp/dpk_response.txt

# Check what it would run
# Should show: ./psft-dpk-setup.sh --silent --response_file=/tmp/dpk_response.txt
```

**Expected:**
- ✅ Command shown correctly
- ✅ Finds setup script
- ✅ No execution

## Phase 2: PS_HOME Install (45 min)

**This does a real installation - PS_HOME only (no domains)**

### Create Minimal Response File
```bash
cat > /tmp/response_pshome.txt <<EOF
env_type=midtier
psft_base_dir="$DPK_BASE"
deploy_only=true
deploy_type=tools_home
EOF

cat /tmp/response_pshome.txt
```

### Run Setup
```bash
# Ensure env vars set
source /tmp/dpk-env.sh

# Run setup (takes ~30-45 min)
psa dpk setup \
  --response-file /tmp/response_pshome.txt \
  --log-file /tmp/setup_pshome.log

# Monitor in another terminal
tail -f /tmp/setup_pshome.log
```

### Verify Installation
```bash
# Check PS_HOME created
ls -la $DPK_BASE/pt/
ls -la $DPK_BASE/pt/ps_home8.62.*/bin/

# Check Puppet installed
$DPK_BASE/psft_puppet_agent/puppet/bin/puppet --version

# Check status
psa dpk status

# Check log for errors
grep -i error /tmp/setup_pshome.log | grep -v "0 errors"
grep -i fail /tmp/setup_pshome.log
grep "Setup Process Ended" /tmp/setup_pshome.log
```

**Expected:**
- ✅ PS_HOME installed at `$DPK_BASE/pt/ps_home8.62.xx/`
- ✅ Puppet installed at `$DPK_BASE/psft_puppet_agent/`
- ✅ Log shows success
- ✅ `psa dpk status` reports "ready for provisioning"

## Phase 3: Full Mid-Tier (Optional, 2 hrs)

⚠️ **Only run if Phase 2 succeeded and you have a test database**

### Prerequisites
```bash
# MUST have:
# 1. Test database (NOT production!)
# 2. Database accessible from test server
# 3. Credentials in response file

# Verify database connectivity
tnsping FSCMQQ  # or your test DB
sqlplus people/password@FSCMQQ  # test credentials
```

### Run Full Setup
```bash
source /tmp/dpk-env.sh

# Use full response file from Phase 1, Test 3
psa dpk setup \
  --response-file /tmp/dpk_response.txt \
  --log-file /tmp/setup_full.log \
  --debug

# Monitor (will take 1.5-2 hours)
tail -f /tmp/setup_full.log
```

### Verify Domains
```bash
# Check domains created
ls -la $PS_CFG_HOME/appserv/
ls -la $PS_CFG_HOME/prcs/
ls -la $PS_CFG_HOME/pia/

# Try starting domains
psadmin -c start -d APPDOM
psadmin -p start -d PRCSDOM
psadmin -w start -d peoplesoft

# Check status
psadmin -c status -d APPDOM
psadmin -p status -d PRCSDOM
psadmin -w status -d peoplesoft

# Check web access
curl http://localhost:8000/ps/signon.html
# or
curl http://[hostname]:8000/ps/signon.html
```

**Expected:**
- ✅ All domains created
- ✅ Domains start successfully
- ✅ PIA signon page loads

## Troubleshooting

### Stage Failed
```bash
# Check zip file patterns
ls -la $DPK_REPO/*.zip
# Should match: *_1of*.zip or *-01.zip

# Check permissions
ls -ld $DPK_INSTALL
ls -la $DPK_REPO/
```

### Setup Failed - Script Not Found
```bash
# Verify extraction
ls -la $DPK_INSTALL/setup/
file $DPK_INSTALL/setup/psft-dpk-setup.sh

# Make executable
chmod +x $DPK_INSTALL/setup/psft-dpk-setup.sh
```

### Setup Failed - Missing Prerequisites
```bash
# Check for ncurses
ls -la /lib64/libncursesw.so.5 /usr/lib64/libncursesw.so.5

# Install if missing
sudo dnf install ncurses-compat-libs
# or
sudo yum install ncurses-compat-libs
```

### Setup Failed - Database Connection
```bash
# Check database running
tnsping FSCMQQ

# Check credentials
sqlplus people/password@FSCMQQ

# Check listener
lsnrctl status

# Check response file
grep db_name /tmp/dpk_response.txt
grep db_host /tmp/dpk_response.txt
grep db_port /tmp/dpk_response.txt
```

### Setup Failed - Puppet Errors
```bash
# Check log for specific errors
grep "\[FAILED\]" /tmp/setup_*.log
grep -A10 -B10 "Error:" /tmp/setup_*.log

# Check disk space
df -h $DPK_BASE

# Check permissions
ls -la $DPK_BASE/
```

## Success Criteria

### Phase 1 (Quick Tests) ✅
- [x] `psa dpk stage` copies all zips
- [x] First zip extracted, setup script found
- [x] Response template generates
- [x] Response file edited with real values
- [x] Dry run shows correct command

### Phase 2 (PS_HOME) ✅
- [x] Setup completes without errors
- [x] PS_HOME directory created
- [x] Puppet installed
- [x] `psa dpk status` shows ready

### Phase 3 (Full Mid-Tier) ✅
- [x] All domains created
- [x] Domains start successfully
- [x] PIA accessible via web
- [x] Integration broker configured

## Cleanup

```bash
# Remove test installation
rm -rf $DPK_INSTALL
rm -rf $DPK_BASE
rm /tmp/dpk-env.sh
rm /tmp/dpk_response.txt
rm /tmp/response_pshome.txt
rm /tmp/setup_*.log

# Verify cleaned
ls /tmp/dpk-*
```

## Reference Files

- Full plan: `DPK_VALIDATION_PLAN.md`
- Config reference: `FSCM55_CONFIG_REFERENCE.md`
- Response file template: `dpk_response_fscm55.txt`

## Estimated Time

| Phase | Duration | Can Skip? |
|-------|----------|-----------|
| Prerequisites | 5 min | No |
| Phase 1 (Quick Tests) | 15 min | No |
| Phase 2 (PS_HOME) | 45 min | No |
| Phase 3 (Full Mid-Tier) | 2 hrs | Yes* |
| **Total** | **~3 hrs** | |

\* Phase 3 can be skipped if Phase 2 validates core functionality
