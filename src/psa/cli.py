"""Main CLI application for psa tools."""

from typing import Optional

import typer
from rich.console import Console

from psa import __version__
from psa.commands import cache, config, domain, dpk, ops, init, secrets

console = Console()

# Main application
app = typer.Typer(
    name="psa",
    help="PeopleSoft Administration Tools",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register subcommands
app.add_typer(domain.app, name="domain")
app.add_typer(dpk.app, name="dpk")
app.add_typer(secrets.app, name="secrets")
app.add_typer(cache.app, name="cache")
app.add_typer(ops.app, name="ops")
app.add_typer(config.app, name="config")

# Direct commands (not subgroups)
app.command(name="init")(init.init)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"psa version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """
    PeopleSoft Administration Tools.

    A unified CLI for managing PeopleSoft domains, secrets, and utilities.
    """
    pass


if __name__ == "__main__":
    app()
