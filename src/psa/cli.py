"""Main CLI application for psa tools."""

from typing import Optional

import typer

from psa import __version__
from psa.commands import config, domain, dpk, ops
from psa.core.output import Verbosity, console, set_verbosity

# Main application
app = typer.Typer(
    name="psa",
    help="[bold]PSA-CLI[/bold]\n\nA PeopleSoft Administration Tool from psadmin.io",
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
        help="Show version and exit",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output except errors"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    if quiet:
        set_verbosity(Verbosity.QUIET)
    elif verbose:
        set_verbosity(Verbosity.VERBOSE)


if __name__ == "__main__":
    app()
