# Quickstart

This walkthrough takes you from a fresh install to a running PeopleSoft domain managed via psa. It assumes you have a PeopleSoft environment provisioned (or are about to provision one with `psa dpk`).

## 1. Configure

Run the interactive setup. psa will try to auto-detect `PS_HOME`, `PS_CFG_HOME`, and the runtime user:

```bash
psa config setup
```

Or skip prompts and accept all detected defaults:

```bash
psa config setup --yes
```

Or be explicit:

```bash
psa config setup \
  --ps-cfg-home /u01/app/psoft/cfg \
  --runtime-user psadm2
```

This writes `~/.config/psa/config.yaml`. Inspect it any time:

```bash
psa config show
```

## 2. Discover domains

```bash
psa domain list
```

You should see your provisioned app, web, and process scheduler domains. To pipe into other tools:

```bash
psa domain list --json
```

## 3. Check a domain

```bash
psa domain status APPDOM
```

This shows the running state of every server process in the domain.

## 4. Lifecycle operations

```bash
psa domain start APPDOM      # Start a stopped domain
psa domain stop APPDOM       # Stop a running domain
psa domain restart APPDOM    # Stop, then start
psa domain bounce APPDOM     # Stop, purge, flush, configure, start
```

The `--force` flag (alias `-f`) skips the interactive confirmation on destructive operations.

Run against all domains with `--all`:

```bash
psa domain stop --all
```

## 5. Compare configurations

`psa domain compare` diffs a domain's current config against an archived `.cfx`:

```bash
psa domain compare APPDOM            # Interactive archive picker
psa domain compare APPDOM --archive /path/to/psappsrv.cfx
```

## 6. DPK provisioning (optional)

If you need to stand up a fresh environment, see the [DPK provisioning workflow](dpk/provisioning-workflow.md).

The 10,000-foot view:

```bash
psa dpk stage --version 8.62.04     # Unpack DPK archives
psa dpk setup                        # OS prereqs + Puppet install
psa dpk init                         # Generate hiera.yaml + customer dir
psa dpk sync                         # Pull YAMLs from API / source
psa dpk apply --summary              # Run puppet apply, readable output
```

## What's next?

- [Commands reference](commands/index.md) — every command + every flag
- [DPK workflow](dpk/provisioning-workflow.md) — full PeopleSoft DPK provisioning walkthrough
