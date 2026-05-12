# `psa domain`

Manage PeopleSoft domains (app, web, process scheduler).

## Subcommands

| Command | Description |
|---|---|
| `psa domain list` | List all discovered domains |
| `psa domain status <DOMAIN>` | Show running state of every server in the domain |
| `psa domain start <DOMAIN>` | Start a domain |
| `psa domain stop <DOMAIN>` | Stop a domain |
| `psa domain restart <DOMAIN>` | Stop, then start |
| `psa domain bounce <DOMAIN>` | Stop, purge cache, flush, configure, start |
| `psa domain compare <DOMAIN>` | Compare current config against an archived `.cfx` |

## Common flags

| Flag | Description |
|---|---|
| `--all` | Operate on every discovered domain |
| `-f`, `--force` | Skip the confirmation prompt on destructive operations |
| `-j`, `--json` | Emit JSON instead of Rich tables |
| `-q`, `--quiet` / `-v`, `--verbose` | Adjust output verbosity |

## Examples

```bash
# List all domains as JSON
psa domain list --json

# Status of all domains
psa domain status --all

# Bounce a domain without prompting
psa domain bounce APPDOM --force

# Diff current config against an archive
psa domain compare APPDOM --archive /u01/app/.../psappsrv.cfx
```

## `compare` archive picker

`psa domain compare <DOMAIN>` (no `--archive`) opens an interactive picker showing each `.cfx` archive in the domain's `archive/` directory with its age. Pick one to diff against the live config.

When piped, `compare` outputs a unified diff that handles `%PS_SERVDIR%` variable substitution.

## Status output

`psa domain status` recognizes the following process states from `psadmin` / `tmadmin` output:

- `Started` / `started`
- `Running`
- `Not Started` / `not started`
- `Down`

Web tier (PIA → web rename) routes through `psadmin -w start` / `shutdown` for PeopleTools 8.62.
