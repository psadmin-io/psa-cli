# `psa kit`

!!! warning "Gated command group"
    `psa kit` operates on the private [`psadmin-io/psa-kit`](https://github.com/psadmin-io/psa-kit) repository. It is hidden unless explicitly enabled, and requires SSH access to the kit repo. General users can ignore this group.

## Enable

```bash
psa config set enable_psa_kit true
```

Once enabled, `psa --help` will list the `kit` group.

## Subcommands

| Command | Description |
|---|---|
| `psa kit clone` | Clone `psadmin-io/psa-kit` (SSH preferred, HTTPS fallback) |
| `psa kit update` | Pull latest changes |
| `psa kit status` | Show kit state |

## Authentication

SSH clone uses your existing GitHub SSH key. HTTPS fallback uses `git credential` — useful when SSH is blocked. The kit is private; access must be granted by a psadmin.io maintainer.
