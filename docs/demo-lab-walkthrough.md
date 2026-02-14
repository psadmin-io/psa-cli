# Demo Lab Walkthrough — Domain Commands

> Findings from interactive testing of `psa domain` commands on the demo lab PS server.
> Use this doc for future lab setup and troubleshooting.

## Lab Environment

| Host | IP | User | Role |
|------|----|------|------|
| PS server | 10.6.2.34 | opc | PeopleSoft mid-tier (app, prcs, web) |
| API server | 10.6.2.169 | opc | PSA-OPS API + UI |

**SSH**: `ssh -i ~/.ssh/psaOps.key -J jump.psadmin.cloud opc@10.6.2.34`

**CLI Deploy**: `./scripts/deploy-cli.sh dev` (psa-ops PRs #317, #325)

### PeopleSoft Paths (psadm2 user)

| Variable | Value |
|----------|-------|
| PS_HOME | /opt/oracle/psft/pt/ps_home8.62.04 |
| PS_CFG_HOME | /home/psadm2/psft/pt/8.62 |
| PS_APP_HOME | /opt/oracle/psft/pt/fscm_app_home |
| Domains | /home/psadm2/psft/pt/8.62/appserv/, webserv/ |

---

## Findings

### F1: CLI config has wrong PS Base path

**Severity**: Blocker — no commands work until fixed
**Step**: 1 (`psa domain list`)
**Symptom**: `No domains found — Searched: /u01/app/psoft/cfg`

**Root cause**: `psa config setup` defaulted to `/u01/app/psoft` but this server's PeopleSoft lives at `/opt/oracle/psft` (PS_HOME) with PS_CFG_HOME at `/home/psadm2/psft/pt/8.62`.

**Fix**: Re-run `psa config setup` with correct paths, or edit `~/.config/psa/config.yaml`:
```yaml
ps_base: /opt/oracle/psft   # or wherever PS_HOME parent is
```

**Lab setup note**: The CLI derives PS_CFG_HOME from ps_base by convention (`{ps_base}/cfg`). If the actual PS_CFG_HOME doesn't follow this convention (as on DPK-provisioned servers), the CLI needs to support explicit PS_CFG_HOME override.

**Potential issue to file**: CLI should auto-detect PS_CFG_HOME from psadm2's environment instead of deriving from ps_base.

**Workaround applied**: Manually added `ps_cfg_home` and `ps_home` to config.yaml on the server.

### F2: Discovery crashes on permission error instead of skipping

**Severity**: High — one unreadable domain kills discovery for all domains
**Step**: 1 (`psa domain list`)
**Symptom**: `Error: Permission denied accessing domain paths: [Errno 13] Permission denied: '.../configuration.properties'`

**Root cause**: `run_discovery()` in `discovery.py` catches `PermissionError` and exits immediately. If any single domain directory is unreadable, no domains are returned — even ones that are readable.

The underlying issue: discovery reads config files directly as opc. App/prcs configs are 775 (readable by all), but the PIA `webserv/peoplesoft/` directory is 750 (psadm2:oinstall only). Python's `Path.exists()` raises PermissionError when traversing restricted parent dirs.

**Fix needed**: Discovery should catch PermissionError per-domain (in `discover_pia_domains`, etc.) and skip unreadable domains with a warning, not crash the whole list.

**Lab note**: File permissions on DPK-provisioned servers:
- `appserv/APPDOM/psappsrv.cfg` — 775 (psadm2:oinstall) — readable by opc
- `appserv/prcs/PRCSDOM/psprcs.cfg` — 775 (psadm2:oinstall) — readable by opc
- `webserv/peoplesoft/` — 750 (psadm2:oinstall) — **NOT readable by opc**

### F3: PIA configuration.properties not at expected path

**Severity**: Medium — PIA domains won't be discovered even with permissions fixed
**Step**: 1 (`psa domain list`)

**Root cause**: Discovery checks `webserv/{name}/applications/peoplesoft/configuration.properties` but on this DPK server the file is at:
- `.../applications/peoplesoft/PORTAL.war/WEB-INF/psftdocs/ps/configuration.properties`
- `.../applications/peoplesoft/PSEMHUB.war/envmetadata/config/configuration.properties`

The expected flat path doesn't exist. Discovery code needs updating for DPK-provisioned PIA layout.

**Also note**: `config/config.xml` DOES exist at `webserv/peoplesoft/config/config.xml` (750 perms). If permissions were fixed, the fallback would work — but the `configuration.properties` path is still wrong for DPK layout.

### F4: JSON output leaks encrypted passwords

**Severity**: High — security concern for demo
**Step**: 1 (`psa domain list --json`)
**Symptom**: `--json` output includes full `config_files` array with raw psappsrv.cfg content, including `UserPswd`, `ConnectPswd`, `DomainConnectionPwd` (encrypted but still sensitive).

**Fix needed**: Either strip `config_files` from `--json` list output (already stripped for table output), or redact password fields.

### F5: PRCSDOM status shows "unknown" while APPDOM shows "stopped"

**Severity**: Low — cosmetic inconsistency
**Step**: 1 (`psa domain list`)
**Root cause**: `_check_prcs_status()` in domain.py always returns "unknown" (hardcoded). `_check_appserver_status()` checks for TUXLOG existence but defaults to "stopped". Neither actually checks running processes — they're heuristic-based file checks.

**Note**: The actual status command (step 2) uses psadmin, which is accurate. This is just the list view's inline status.

### F6: `_find_domain()` discovers ALL types, ignores `--type` filter — complete blocker

**Severity**: BLOCKER — all domain commands (status, start, stop, etc.) fail
**Step**: 2 (`psa domain status APPDOM`)
**Symptom**: Raw Python traceback (PermissionError) even with `--type app`

**Root cause**: `_find_domain()` → `discover_all_homes()` → `discover_all()` which discovers app + prcs + PIA. The `domain_type` arg only filters results *after* full discovery. So PIA permission errors block app/prcs commands too.

Two sub-issues:
1. `_find_domain()` should scope discovery to requested type when `--type` is provided
2. `_find_domain()` has no error handling — unlike `run_discovery()` (used by `list`), it shows raw tracebacks instead of clean error messages

**Workaround**: Fix permissions on server (`chmod o+rx /home/psadm2/psft/pt/8.62/webserv/peoplesoft/`) to unblock testing, then fix code properly later.

### F7: Status parser doesn't recognize "is not started" output

**Severity**: High — domains always show "unknown" when stopped
**Step**: 2 (`psa domain status`)
**Symptom**: `APPDOM: unknown` and `PRCSDOM: unknown` when both are stopped

**Root cause**: `_parse_status_output()` checks:
- App: "not booted" / "no processes" → stopped
- Prcs: "not running" / "no process" → stopped

But actual psadmin output says "is not started" for both. The parser doesn't match this phrase.

**Fix needed**: Add "is not started" and "not started" to the stopped detection patterns.

**Also noted**: APPDOM `--full` output repeats the same line 3 times — psadmin runs status for multiple subsections. Not a bug per se but could confuse users.

### F8: `--report` fails without prior `psa ops report`

**Severity**: Low — expected behavior, but warning could be clearer
**Step**: 2 (`psa domain status --report`)
**Symptom**: `Warning: No cached domain ID for 'APPDOM'; run 'psa ops report' first`

This is working as designed — domain IDs are cached during `psa ops report`. Just noting for demo flow: must run `psa ops report` before `--report` flag works.

### Step 1 Summary

| Test | Result |
|------|--------|
| `psa domain list` (no type) | FAIL — PermissionError on PIA kills all discovery (F2) |
| `psa domain list --type app` | PASS — shows APPDOM with correct table |
| `psa domain list --type prcs` | PASS — shows PRCSDOM |
| `psa domain list --type pia` | FAIL — PermissionError (F2) |
| `psa domain list --type App` (case) | PASS — case-insensitive works |
| `psa domain list --json` | PARTIAL — works but leaks passwords (F4) |
| No domains edge case | PASS — shows "No domains found" with search path |

### F9: Stop/kill on already-stopped domain shows empty error message

**Severity**: Medium — poor UX for demo
**Step**: 4 (`psa domain stop APPDOM`)
**Symptom**: `Error: Failed to stop domain:` — message ends with colon, no explanation
**Exit code**: 40 (from psadmin)

**Root cause**: psadmin returns non-zero with empty stdout when stopping a stopped domain. The CLI formats `result.output` into the error which is empty.

**Fix needed**: Detect "already stopped" case and print a success/info message instead of an error. Alternatively, check status before stop and skip gracefully.

### F10: APPDOM start fails — PSPPMSRV initialization failure

**Severity**: Server issue (not CLI bug)
**Step**: 3 (`psa domain start APPDOM`)
**Symptom**: PSPPMSRV fails during Application initialization, triggers Tuxedo cascade shutdown

**Root cause**: Likely database connectivity — PSPPMSRV needs DB connection during init. The CLI correctly shows psadmin output and exits non-zero. Not a code issue.

**Lab setup note**: Before demo, verify DB connectivity. Check `$PS_CFG_HOME/appserv/APPDOM/LOGS/` for Tuxedo logs.

### F11: PRCSDOM flush fails with Tuxedo error

**Severity**: Server issue (not CLI bug)
**Step**: 8 (`psa domain flush PRCSDOM`)
**Symptom**: "Cleaning up of IPC resources failed" with Tuxedo "boot mode" error

Likely no IPC resources to clean. CLI correctly reports the failure.

### Step 2 Summary

| Test | Result |
|------|--------|
| `psa domain status APPDOM` | FAIL — shows "unknown" instead of "stopped" (F7) |
| `psa domain status PRCSDOM` | FAIL — same (F7) |
| `psa domain status APPDOM --full` | PASS — shows raw psadmin output |
| `psa domain status APPDOM --json` | PASS — structured JSON, status still "unknown" |
| `psa domain status APPDOM --report` | WARN — needs prior `psa ops report` (F8) |
| `psa domain status FAKENAME` | PASS — clean error message |

### Steps 3-12 Summary

| Test | Result |
|------|--------|
| `psa domain start APPDOM` | FAIL — server issue, PSPPMSRV init failure (F10) |
| `psa domain stop APPDOM` (already stopped) | FAIL — empty error message (F9) |
| `psa domain stop APPDOM --force` | FAIL — same as stop (F9) |
| `psa domain restart APPDOM` | PARTIAL — warns on stop, fails on start (server) |
| `psa domain bounce APPDOM` | PARTIAL — nice 5-step output, fails on start (server) |
| `psa domain purge APPDOM` | PASS |
| `psa domain flush APPDOM` | PASS |
| `psa domain flush PRCSDOM` | FAIL — server/Tuxedo issue (F11) |
| `psa domain configure APPDOM` | PASS |
| `psa domain kill APPDOM` (stopped) | FAIL — empty error message (F9) |
| `psa domain reconfigure APPDOM` | PARTIAL — 3-step output, fails on start (server) |
| `psa domain compare APPDOM` | FAIL — no domain in API (needs `psa ops report` first) |
| PIA commands (flush/configure/reconfigure) | BLOCKED — PIA not discoverable (F2/F3) |

---

## Fixes Applied During Walkthrough

### Fix 1: Resilient discovery + scoped find_domain (F2, F6)

**PR**: https://github.com/psadmin-io/psa-cli/pull/21 (merged to staging)

Changes:
- Discovery methods catch `PermissionError` per-domain, skip unreadable domains
- `find_domain()` scopes to requested type when `--type` given
- `_find_domain()` in commands catches errors cleanly (no raw tracebacks)

### Fix 2: Manual config correction (F1)

Updated `/home/opc/.config/psa/config.yaml` on 10.6.2.34:
```yaml
ps_base: /opt/oracle/psft
ps_cfg_home: /home/psadm2/psft/pt/8.62
ps_home: /opt/oracle/psft/pt/ps_home8.62.04
```

### Fix 3: Demo lab findings batch (F1, F3, F5, F7, F9)

**PR**: https://github.com/psadmin-io/psa-cli/pull/24 (merged to staging)

Changes:
- F1: Auto-detect PS paths from runtime user env via sudo; add `ps_app_home`/`ps_cust_home` to config
- F3: PIA discovery uses `config.xml` for existence, globs DPK WAR path for `configuration.properties`
- F5: PRCS/PIA inline status checks filesystem markers (TUXLOG, PIA.pid) instead of hardcoded "unknown"
- F7: Status parser recognizes "is not started" for app/prcs domains
- F9: Fallback error message when psadmin returns empty output on stop/kill

### Fix 4: Status parser for tmadmin process table (F7 follow-up)

**PR**: https://github.com/psadmin-io/psa-cli/pull/25 (merged to staging)

psadmin on this server returns raw tmadmin tables instead of "X processes running" summary. Detect BBL + "Prog Name" header as running indicator.

### Fix 5: PRCS "Started" pattern

**PR**: https://github.com/psadmin-io/psa-cli/pull/26 (merged to staging)

psadmin returns just "Started" for running prcs domains.

### Fix 6: UX polish batch (PRs 22, 27-35)

| PR | Change |
|----|--------|
| [#22](https://github.com/psadmin-io/psa-cli/pull/22) | `SudoFileOps` abstraction — CLI reads config files via sudo |
| [#27](https://github.com/psadmin-io/psa-cli/pull/27) | Global `--quiet`/`--verbose` flags + Rich spinners on all domain commands |
| [#30](https://github.com/psadmin-io/psa-cli/pull/30) | `configure` stops domain first, graceful already-stopped handling |
| [#31](https://github.com/psadmin-io/psa-cli/pull/31) | `run_step` shows `~` warning icon for already-stopped domains |
| [#32](https://github.com/psadmin-io/psa-cli/pull/32) | `psa config set` command, always prompt in all-mode |
| [#33](https://github.com/psadmin-io/psa-cli/pull/33) | `-q`/`-v` flags on every domain subcommand |
| [#34](https://github.com/psadmin-io/psa-cli/pull/34) | Graceful already-purged handling + summary only for multi-domain |
| [#35](https://github.com/psadmin-io/psa-cli/pull/35) | `~` warning icon for already-empty purge |

### Fix 7: Domain compare (PRs 36-39)

`psa domain drift` replaced by `psa domain compare` with archive-based diffing:

| PR | Change |
|----|--------|
| [#36](https://github.com/psadmin-io/psa-cli/pull/36) | Renamed `drift` → `compare`, moved `set-env` to `ops` subcommand |
| [#37](https://github.com/psadmin-io/psa-cli/pull/37) | Fixed `RawConfigParser` for `%PS_SERVDIR%` tokens in .cfg files |
| [#38](https://github.com/psadmin-io/psa-cli/pull/38) | Show backup filename in no-diff output |
| [#39](https://github.com/psadmin-io/psa-cli/pull/39) | Interactive archive picker (select which backup to compare against) |

---

## Re-test Results (2026-02-12)

All domain commands re-tested after deploying fixes 3-5.

| Test | Result | Notes |
|------|--------|-------|
| `psa domain list` | PASS | All 3 domains (app, prcs, pia) discovered, status "stopped" |
| `psa domain list --type app` | PASS | |
| `psa domain list --json` | PASS | PIA config parsed from DPK WAR path. F4 (passwords) still open |
| `psa domain status APPDOM` | PASS | Shows "running" (tmadmin table parsed correctly) |
| `psa domain status PRCSDOM` | PASS | Shows "running" ("Started" parsed) or "stopped" |
| `psa domain status peoplesoft --type pia` | PASS | Shows "stopped" |
| `psa domain start APPDOM` | PASS | |
| `psa domain start PRCSDOM` | PASS | |
| `psa domain stop APPDOM` | PASS | |
| `psa domain stop PRCSDOM` | PASS | |
| `psa domain stop PRCSDOM` (already stopped) | PASS | "Domain may already be stopped" (F9 fixed) |
| `psa domain bounce APPDOM` | PASS | Full 5-step cycle, domain running after |
| `psa domain bounce PRCSDOM` | PASS | Full 5-step cycle, domain running after |
| `psa domain reconfigure APPDOM` | PASS | 3-step cycle |
| `psa domain purge APPDOM` | PASS | |
| `psa domain flush APPDOM` | PASS | |
| `psa domain configure APPDOM` | PASS | |
| `psa domain kill peoplesoft --type pia` | PASS | |
| `psa domain start peoplesoft --type pia` | NOTE | psadmin returns 0 but WebLogic stays stopped — server issue |
| `psa domain stop peoplesoft --type pia` | NOTE | Times out after 120s when WebLogic is stuck — server issue |
| `psa domain compare APPDOM` | TODO | Interactive archive picker — not yet tested on server |
| `psa domain compare APPDOM --latest` | TODO | Compare against latest backup — not yet tested |
| `psa domain compare APPDOM --ops` | TODO | Compare against API config — not yet tested |

### PIA Server Issue

PIA (WebLogic) won't stay running — `startPIA.sh` returns 0 but status immediately shows "stopped". `stopPIA.sh` hangs when WebLogic is stuck. Not a CLI bug. Needs investigation on server (check WebLogic logs at `$PS_CFG_HOME/webserv/peoplesoft/servers/PIA/logs/`).

---

## Demo Flow Mapping

Maps this walkthrough's tested commands to the [10-step demo flow](../CLAUDE.md#may-2026-demo-goals):

| Demo Step | Description | CLI Command(s) | Walkthrough Status |
|-----------|-------------|----------------|-------------------|
| 1 | Training envs pre-built with DPK | — (infra) | N/A |
| 2 | Attendee installs PSA CLI | `pip install psa-cli` / `deploy-cli.sh` | Covered (Lab Environment) |
| 3 | CLI registers node with API | `psa ops register` | Not tested in walkthrough |
| 4 | CLI discovers config, pushes to API | `psa ops report` | Prereq noted (F8) |
| 5 | Attendee sees config in UI | — (UI) | N/A |
| 6 | Manually change psappsrv.cfg | (edit file on server) | Manual step |
| 7 | Detect domain config drift | `psa domain compare APPDOM --ops` | TODO (Fix 7 deployed, not tested) |
| 8 | Change DPK/Hiera config in UI | — (UI) | N/A |
| 9a | Compare local Hiera vs API | `psa dpk data compare` | [psa-cli#40](https://github.com/psadmin-io/psa-cli/issues/40) |
| 9b | Pull new config | `psa dpk data sync` | Done |
| 9c | Apply Puppet | `psa dpk apply` | Done |
| 10 | Re-capture config to API | `psa ops report` | Prereq noted (F8) |

---

## Outstanding Issues

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F4 | `--json` output leaks encrypted passwords | High | [#23](https://github.com/psadmin-io/psa-cli/issues/23) — open |
| — | Generate sudoers file for psa sudo mode | Medium | [#14](https://github.com/psadmin-io/psa-cli/issues/14) — open |
| PIA | WebLogic won't start/stay running | Medium | Server issue — needs investigation |
| — | `domain compare` not yet tested on lab server | Low | Pending live test (PRs 36-39 deployed) |

### Resolved Issues (closed)

| # | Issue | Resolved by |
|---|-------|-------------|
| [#28](https://github.com/psadmin-io/psa-cli/issues/28) | Configure: add stop step, --restart flag | PR #30 |
| [#29](https://github.com/psadmin-io/psa-cli/issues/29) | Handle already-stopped domains gracefully | PRs #30, #31 |

### Server Issues (not CLI bugs)
- ~~F11: PRCSDOM flush fails — Tuxedo IPC issue~~ **Resolved**: domain had never been booted so no IPC existed. After configure+start+stop, flush works fine. Not a bug — psadmin's error message is just misleading.

### Server Issues Fixed

**F10: APPDOM start fails (PSPPMSRV init) — stale hostname from boot clone**

Root cause: Boot clone left old hostname `psaops-node-fscm-55.public.psaopsdev.oraclevcn.com` in three places:
1. `/opt/oracle/psft/db/tnsnames.ora` (HOST=)
2. `/opt/oracle/psft/db/oracle-server/19.3.0.0/network/admin/listener.ora` (HOST=)
3. Oracle `local_listener` DB parameter

DNS returned NXDOMAIN for the old hostname → listener couldn't bind → DB couldn't register → PSPPMSRV couldn't connect.

Fix applied:
```bash
# 1. Update tnsnames.ora and listener.ora: replace old hostname with localhost
sudo sed -i 's/psaops-node-fscm-55.public.psaopsdev.oraclevcn.com/localhost/g' \
  /opt/oracle/psft/db/tnsnames.ora \
  /opt/oracle/psft/db/oracle-server/19.3.0.0/network/admin/listener.ora

# 2. Start listener (was down because it couldn't bind to old hostname)
sudo -u oracle2 bash -lc 'lsnrctl start psft_listener'

# 3. Fix DB local_listener parameter and re-register
sudo -u oracle2 bash -lc 'export ORACLE_SID=CDBFSCM; sqlplus -s / as sysdba <<EOF
alter system set local_listener="(ADDRESS=(PROTOCOL=TCP)(HOST=localhost)(PORT=1521))" scope=both;
alter system register;
EOF'
```

**Lab setup note**: After any boot clone, check these three locations for stale hostnames. The DB user is `oracle2` (not `oracle`), ORACLE_SID is `CDBFSCM`, and ORACLE_SID is NOT set in oracle2's profile — must export it explicitly.
