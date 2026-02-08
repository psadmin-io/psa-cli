"""DPK/Puppet operations commands."""

import typer

# Import core DPK commands
from psa.commands.dpk.core import (
    stage,
    setup,
    prereq,
    postcfg,
    cleanup,
    status,
    apply,
    hiera,
    site,
    modules,
    sync,
)

# Import data subcommand
from psa.commands.dpk import data

# Create main dpk app
app = typer.Typer(
    name="dpk",
    help="DPK/Puppet operations (stage, setup, apply, status)",
    no_args_is_help=True,
)

# Add core commands directly to dpk
app.command("stage")(stage)
app.command("setup")(setup)
app.command("prereq")(prereq)
app.command("postcfg")(postcfg)
app.command("cleanup")(cleanup)
app.command("status")(status)
app.command("apply")(apply)
app.command("hiera")(hiera)
app.command("site")(site)
app.command("modules")(modules)
app.command("sync")(sync)

# Add data subcommand
app.add_typer(data.app, name="data")
