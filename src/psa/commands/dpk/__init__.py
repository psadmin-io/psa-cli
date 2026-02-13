"""DPK lifecycle management commands."""

import typer

# Import core DPK commands
from psa.commands.dpk.core import (
    apply,
    cleanup,
    setup,
    stage,
    status,
    sync,
)

# Import data subcommand
from psa.commands.dpk import data

# Create main dpk app
app = typer.Typer(
    name="dpk",
    help="Manage DPK lifecycle",
    no_args_is_help=True,
)

# Add core commands directly to dpk (alphabetized)
app.command("apply")(apply)
app.command("cleanup")(cleanup)
app.command("setup")(setup)
app.command("stage")(stage)
app.command("status")(status)
app.command("sync")(sync)

# Add data subgroup
app.add_typer(data.app, name="data")
