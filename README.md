<p align="center">
  <img src="docs/assets/io_blue_400.png" alt="psadmin.io" width="280">
</p>

<h1 align="center">psa-cli</h1>

<p align="center">
  <em>A unified command-line tool for PeopleSoft administration.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: Beta">
  <img src="https://img.shields.io/badge/python-3.9+-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/PeopleTools-8.62-1E9CF0" alt="PeopleTools 8.62">
</p>

---

`psa` is a PeopleSoft administration CLI that streamlines daily operations across domains, DPK provisioning, and configuration. It wraps `psadmin`, the DPK installer, and Puppet apply with a consistent, scriptable interface — and produces output that's pleasant to read in a terminal and parseable as JSON when you need it.

> :warning: **Beta.** psa-cli is pre-1.0. The CLI surface, config schema, and command behavior may change before 1.0. Not yet recommended for production use.

## Documentation

Full docs: **<https://cli.psadmin.io>** (commands reference, DPK provisioning workflow, configuration guide).

## Highlights

- **Domain lifecycle** — list, status, start, stop, restart, bounce, compare. Rich output + `--json`.
- **DPK provisioning** — `stage → setup → init → sync → apply → cleanup`, with a 3-tier Hiera layout and custom module install.
- **`dpk apply --summary`** — filtered, readable Puppet output with surfaced errors.
- **Discovery** — find local PeopleSoft domains and optionally report them upstream.
- **Resilient sudo** — file operations transparently escalate when the runtime user can't write.

## Requirements

- Python 3.9+
- Linux (Oracle Linux 8/9, RHEL 8/9 tested)
- PeopleTools 8.62

You can also use the Python shipped with the PeopleSoft DPK or `$PS_HOME/python`.

## Install

PyPI release is planned. For 0.3.0, install from the GitHub release wheel:

```bash
pip install https://github.com/psadmin-io/psa-cli/releases/download/v0.3.0/psa_cli-0.3.0-py3-none-any.whl
```

Or from source:

```bash
git clone https://github.com/psadmin-io/psa-cli.git
cd psa-cli
pip install -e .
```

## Quick start

```bash
# Initialize with auto-detected paths (interactive)
psa config setup

# Or accept all detected defaults non-interactively
psa config setup --yes

# Or specify paths explicitly
psa config setup --ps-cfg-home /u01/app/psoft/cfg --runtime-user psadm2
```

Then:

```bash
psa domain list                    # List discovered domains
psa domain status APPDOM           # Check a domain
psa domain bounce APPDOM           # Full bounce (stop, purge, flush, configure, start)
psa dpk apply --summary            # Run puppet apply with readable output
```

See the [Quickstart](https://psadmin-io.github.io/psa-cli/quickstart/) for the full happy-path walkthrough.

## Configuration

Configuration lives in `~/.config/psa/config.yaml`. Most paths are auto-detected. Example:

```yaml
ps_cfg_home: /u01/app/psoft/cfg
runtime_user: psadm2
dpk_base: /u01/app/psoft
dpk_home: /u01/app/psoft/dpk
dpk_cust_home: /u01/app/psoft/dpk-cust
```

### Environment variables

| Variable | Purpose |
|---|---|
| `PS_CFG_HOME` | PeopleSoft config home |
| `PS_HOME`     | PeopleSoft home |
| `DPK_BASE`    | DPK install parent dir; used by `dpk setup` / `cleanup` / `status` |
| `DPK_HOME`    | DPK install dir, conventionally `$DPK_BASE/dpk`; used by `dpk sync` / `apply` / `init` |
| `DPK_CUST_HOME` | Customer DPK customizations dir; used by `dpk init` / `module install` / `sync` |

## Contributing

Bug reports and feature requests are welcome via [GitHub Issues](https://github.com/psadmin-io/psa-cli/issues). See [SECURITY.md](SECURITY.md) for reporting security issues privately.

## License

[MIT](LICENSE) © psadmin.io
