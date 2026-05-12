# Contributing

Thanks for your interest in improving psa-cli.

## Reporting bugs / requesting features

- File an issue: <https://github.com/psadmin-io/psa-cli/issues/new/choose>
- Use the **Bug report** template for defects and **Feature request** for enhancements.
- For **security issues**, see [SECURITY.md](https://github.com/psadmin-io/psa-cli/blob/main/SECURITY.md) and report privately.

## Development setup

```bash
git clone https://github.com/psadmin-io/psa-cli.git
cd psa-cli
uv sync --extra dev
```

Run tests:

```bash
uv run pytest -v
```

Lint:

```bash
uv run ruff check .
```

## Branching

- `main` — release branch. Tagged releases live here.
- `staging` — integration branch. Feature branches PR into staging; staging is merged to main per release.
- `feat/<name>` / `fix/<name>` — feature branches.

## Pull requests

1. Branch from `staging`.
2. Run `pytest` and `ruff check` locally.
3. Open a PR against `staging`. CI runs on push/PR.
4. Use the PR template; reference any related issues.

## Commit style

Short, concise, present-tense. Sacrifice grammar for clarity. Example:

```
domain compare: handle %PS_SERVDIR% in raw-config diff
```
