# psa-cli

psadmin.io CLI - a unified command-line tool for managing PeopleSoft domains.

## Prerequisites

psa-cli requires Python 3.9+.

```bash
sudo dnf install python3.9
```

You may also be able to use the Python shipped with the PeopleSoft DPK or `$PS_HOME/python`.

## Installation

```bash
pip install psa-cli
```

Or install from source:

```bash
pip install -e .
```

## Quick Start

```bash
# Initialize with auto-detected paths (interactive)
psa config setup

# Accept all detected defaults non-interactively
psa config setup --yes

# Or specify paths explicitly
psa config setup --ps-cfg-home /u01/app/psoft/cfg --runtime-user psadm2
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

## Configuration

Configuration is stored in `~/.config/psa/config.yaml`.

### Example config:

```yaml
ps_cfg_home: /u01/app/psoft/cfg
domain_user: psadm2
```

## Environment Variables

- `PS_CFG_HOME` - PeopleSoft config home path
- `PS_HOME` - PeopleSoft home path

## License

MIT
