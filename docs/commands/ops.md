# `psa ops`

Manage the connection between this node and a PSA-OPS server.

## Subcommands

| Command | Description |
|---|---|
| `psa ops setup --url <url>` | Register this node with PSA-OPS, then auto-register discovered domains |
| `psa ops register [DOMAIN...]` | Push locally-discovered domains to PSA-OPS |
| `psa ops set-env <DOMAIN> <ENV>` | Assign an environment to a domain in PSA-OPS |
| `psa ops environments` | List environments configured in PSA-OPS |
| `psa ops nodes` | List nodes registered in PSA-OPS |
| `psa ops status` | Show local config + connection status |
| `psa ops compare <DOMAIN> <DOMAIN>...` | Compare config across 2+ domains via PSA-OPS |

## `setup`

```bash
psa ops setup --url http://psaops.local:8000
psa ops setup --url http://psaops.local:8000 --role app --yes
psa ops setup --url http://psaops.local:8000 --skip-domains
```

Connects to PSA-OPS, picks an environment (auto-detected from domain `db_name` when possible), registers the node, then auto-runs `psa ops register` to push discovered domains. Pass `--skip-domains` to register the node only.

| Flag | Description |
|---|---|
| `-r`, `--url` | PSA-OPS URL (required) |
| `-e`, `--environment-id` | Skip env auto-detection and use this UUID |
| `--role` | Node role: `app`, `web`, `prcs`, `mid`, `webapp` |
| `-y`, `--yes` | Non-interactive mode (accept detected defaults) |
| `--skip-domains` | Don't auto-register domains after node setup |

## `register`

```bash
psa ops register                     # all discovered domains
psa ops register APPDOM              # one
psa ops register APPDOM PRCSDOM      # subset
psa ops register --yes               # non-interactive
psa ops register --json | jq .
```

Discovers domains locally and pushes them to PSA-OPS using the node's anchor environment (`config.ops.environment_id`). Idempotent — the server upserts, so re-running is safe.

For nodes hosting domains from multiple environments, register first, then use `psa ops set-env` to reassign individual domains:

```bash
psa ops register --yes
psa ops set-env IHLAB1 IHLAB
psa ops set-env IHLAB2 IHLAB
```

## `set-env`

```bash
psa ops set-env APPDOM dev
psa ops set-env APPDOM dev --type app
```

Assigns an environment to a single domain. Resolves domain and environment by name (case-insensitive for env). Use `--type` (`app`/`prcs`/`web`) to disambiguate when multiple domains share a name.

## `compare`

```bash
psa ops compare APPDOM1 APPDOM2
psa ops compare APPDOM1 APPDOM2 --type psappsrv.cfg
psa ops compare APPDOM1 APPDOM2 APPDOM3 --all
```

Fetches a config comparison from PSA-OPS for 2+ registered domains. Only `different` and `missing` rows shown by default; `--all` includes `same`.

## Common flags

| Flag | Description |
|---|---|
| `-y`, `--yes` | Skip confirmation prompts |
| `-j`, `--json` | Emit JSON instead of Rich tables |
| `-q`, `--quiet` / `-v`, `--verbose` | Adjust output verbosity |
