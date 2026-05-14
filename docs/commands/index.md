# Commands overview

psa is organized into command groups. Each group has a `--help` flag listing its subcommands.

| Group | Purpose | Reference |
|---|---|---|
| `psa config` | Configure psa: paths, runtime user, defaults | [config](config.md) |
| `psa domain` | Manage PeopleSoft domains: lifecycle, status, compare | [domain](domain.md) |
| `psa dpk` | DPK provisioning: stage, setup, init, sync, apply, cleanup | [dpk](dpk.md) |
| `psa ops` | Connect to PSA-OPS: setup, register domains, compare across nodes | [ops](ops.md) |

## Global flags

| Flag | Description |
|---|---|
| `-V`, `--version` | Print version and exit |
| `-q`, `--quiet` | Suppress all output except errors |
| `-v`, `--verbose` | Show detailed output |

## Output modes

Most commands that produce structured data support `--json`:

```bash
psa domain list --json | jq '.[] | select(.type == "app")'
```

When stdout is a TTY, psa renders Rich tables, spinners, and color. When piped, it falls back to plain text — safe for scripts.

## Configuration

psa reads `~/.config/psa/config.yaml`. See [`psa config`](config.md) for the full schema and editing commands.
