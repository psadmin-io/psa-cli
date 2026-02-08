# psa-cli

PeopleSoft Administration CLI - a unified command-line tool for managing PeopleSoft domains.

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

Run without a hub connection for local domain management:

```bash
# Initialize with auto-detected paths
psa init

# Or specify paths explicitly
psa init --ps-cfg-home /u01/app/psoft/cfg --domain-user psadm2
```

### Hub Mode

Connect to a PSA Ops hub for centralized management:

```bash
psa init --hub-url http://hub.example.com:8000
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
psa discover --push                # Push to hub (requires hub connection)
```

### Hub Integration (when connected)

```bash
psa hub status                     # Check hub connection
psa hub environments               # List environments from hub
```

## Configuration

Configuration is stored in `~/.config/psa/config.yaml`.

### Example config (standalone):

```yaml
ps_cfg_home: /u01/app/psoft/cfg
domain_user: psadm2
```

### Example config (with hub):

```yaml
ps_cfg_home: /u01/app/psoft/cfg
domain_user: psadm2
hub:
  url: http://hub.example.com:8000
  node_id: abc123...
  environment_id: def456...
```

## Environment Variables

- `PS_CFG_HOME` - PeopleSoft config home path
- `PS_HOME` - PeopleSoft home path
- `PSA_HUB_URL` - Hub API URL (overrides config file)

## License

MIT
