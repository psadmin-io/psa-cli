# `psa config`

Configure psa: paths, runtime user, defaults.

## Config file

psa reads `~/.config/psa/config.yaml`. Example:

```yaml
ps_cfg_home: /u01/app/psoft/cfg
ps_home: /u01/app/psoft/PT8.62
ps_base: /u01/app/psoft
runtime_user: psadm2
dpk_base: /u01/app/psoft
dpk_home: /u01/app/psoft/dpk
dpk_cust_home: /u01/app/psoft/dpk-cust
```

## Subcommands

| Command | Description |
|---|---|
| `psa config setup` | Interactive (or `--yes`) first-run configuration |
| `psa config show` | Print resolved config, with sources |
| `psa config set <key> <value>` | Set a single config key |

## `setup` flags

| Flag | Description |
|---|---|
| `-c`, `--ps-cfg-home <path>` | Override auto-detection |
| `-u`, `--runtime-user <name>` | Runtime user (default: `psadm2`) |
| `-y`, `--yes` | Accept all detected defaults non-interactively |

`setup` auto-detects `PS_HOME`, `PS_APP_HOME`, `PS_CUST_HOME` by `sudo su - <runtime_user>` and echoing the user's env. If sudo isn't configured, it falls back to interactive prompts.

## `set`-able keys

`psa config set` accepts:

- `ps_cfg_home`, `ps_home`, `ps_base`
- `dpk_base`, `dpk_home`, `dpk_cust_home`
- `runtime_user`
- ...and any other supported key. See `psa config show` for the full list.

## Example

```bash
# First-run, accept everything
psa config setup --yes

# Then customize one value
psa config set dpk_cust_home /u01/app/psoft/dpk-cust

# Verify
psa config show
```
