"""DPK lifecycle management commands."""

import typer

# Import core DPK commands
from psa.commands.dpk.core import (
    apply,
    cleanup,
    hiera,
    modules,
    postcfg,
    prereq,
    setup,
    site,
    stage,
    status,
    sync,
)

# Import subcommands
from psa.commands.dpk import data
from psa.commands.dpk import repo

# Create main dpk app
app = typer.Typer(
    name="dpk",
    help="Manage DPK lifecycle",
    no_args_is_help=True,
)

# Add core commands directly to dpk (alphabetized)
app.command("apply")(apply)
app.command("cleanup")(cleanup)
app.command("hiera")(hiera)
app.command("modules")(modules)
app.command("postcfg")(postcfg)
app.command("prereq")(prereq)
app.command("setup")(setup)
app.command("site")(site)
app.command("stage")(stage)
app.command("status")(status)
app.command("sync")(sync)

# Add subgroups
app.add_typer(data.app, name="data")
app.add_typer(repo.app, name="repo")
