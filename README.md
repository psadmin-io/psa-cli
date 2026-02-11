# psa-cli

psadmin.io CLI - a unified command-line tool for managing PeopleSoft domains.

## Installation

```bash
pip install psa-cli
```

Or install from source:

```bash
pip install -e .
```

## Quick Start

### Standalone Mode

Run without an API connection for local domain management:

```bash
# Initialize with auto-detected paths
psa init

# Or specify paths explicitly
psa init --ps-cfg-home /u01/app/psoft/cfg --domain-user psadm2
```

### OPS Mode

Connect to a PSA-OPS instance for centralized management:

```bash
psa init --ops-url http://ops.example.com:8000
```

## Commands

### Domain Management

```bash
psa domain list                    # List all domains
psa domain status APPDOM           # Check domain status
psa domain start APPDOM            # Start a domain
psa domain stop APPDOM             # Stop a domain
psa domain restart APPDOM          # Restart a domain
psa domain bounce APPDOM           # Full bounce (stop, purge, flush, configure, start)
```

### Discovery

```bash
psa discover                       # Discover domains on this node
psa discover --json                # Output as JSON
psa discover --report              # Report to API (requires API connection)
```

### OPS Integration (when connected)

```bash
psa ops status                     # Check API connection
psa ops environments               # List environments from API
```

## Configuration

Configuration is stored in `~/.config/psa/config.yaml`.

### Example config (standalone):

```yaml
ps_cfg_home: /u01/app/psoft/cfg
domain_user: psadm2
```

### Example config (with OPS):

```yaml
ps_cfg_home: /u01/app/psoft/cfg
domain_user: psadm2
ops:
  url: http://ops.example.com:8000
  node_id: abc123...
  environment_id: def456...
```

## Environment Variables

- `PS_CFG_HOME` - PeopleSoft config home path
- `PS_HOME` - PeopleSoft home path
- `PSA_OPS_URL` - API URL (overrides config file)

## License

MIT
