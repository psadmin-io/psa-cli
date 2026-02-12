"""Main CLI application for psa tools."""

from typing import Optional

import typer
from rich.console import Console

from psa import __version__
from psa.commands import config, domain, dpk, ops

console = Console()

# Main application
app = typer.Typer(
    name="psa",
    help="PeopleSoft Administration Tools",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

# Register subcommands (alphabetized)
app.add_typer(config.app, name="config")
app.add_typer(domain.app, name="domain")
app.add_typer(dpk.app, name="dpk")
app.add_typer(ops.app, name="ops")


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
    """A unified CLI for managing PeopleSoft domains and DPK deployments."""
    pass


if __name__ == "__main__":
    app()
