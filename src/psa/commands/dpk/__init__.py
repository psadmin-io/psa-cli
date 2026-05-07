"""DPK lifecycle management commands."""

import typer

# Import core DPK commands
from psa.commands.dpk.core import (
    apply,
    cleanup,
    lookup,
    setup,
    stage,
    status,
    sync,
)
from psa.commands.dpk.init import dpk_init

# Import subcommands
from psa.commands.dpk import data
from psa.commands.dpk import facts
from psa.commands.dpk import module
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
app.command("init")(dpk_init)
app.command("lookup")(lookup)
app.command("setup")(setup)
app.command("stage")(stage)
app.command("status")(status)
app.command("sync")(sync)

# Add subgroups (data is hidden; still callable explicitly)
app.add_typer(data.app, name="data", hidden=True)
app.add_typer(facts.app, name="facts")
app.add_typer(module.app, name="module")
app.add_typer(repo.app, name="repo")
