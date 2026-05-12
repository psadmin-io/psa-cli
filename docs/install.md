# Install

## Requirements

- Python 3.9 or newer
- Linux (Oracle Linux 8/9, RHEL 8/9 tested; other distros likely work)
- PeopleTools 8.62 (older versions may work but are unverified)

You can use system Python, the Python shipped with the PeopleSoft DPK, or `$PS_HOME/python`.

## Install Python

=== "Oracle Linux / RHEL"

    ```bash
    sudo dnf install -y python3.11
    ```

=== "Use DPK Python"

    The DPK ships with a recent Python under `$PS_HOME/python`. You can add it to your `PATH` or call it directly:

    ```bash
    $PS_HOME/python/bin/python3 -m pip install ...
    ```

## Install psa-cli

### From the GitHub release

PyPI publishing is planned. For 0.3.0, install from the GitHub release wheel:

```bash
pip install https://github.com/psadmin-io/psa-cli/releases/download/v0.3.0/psa_cli-0.3.0-py3-none-any.whl
```

### From source

```bash
git clone https://github.com/psadmin-io/psa-cli.git
cd psa-cli
pip install -e .
```

## Verify

```bash
psa --version
```

You should see `psa version 0.3.0`.

## Next steps

→ [Quickstart](quickstart.md) to configure psa and run your first commands.
