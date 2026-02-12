"""Output formatting utilities."""

from __future__ import annotations

import json
from enum import IntEnum
from typing import Any, Callable, Optional, TypeVar

from rich.console import Console
from rich.table import Table

T = TypeVar("T")

console = Console()
error_console = Console(stderr=True)


# --- Verbosity ---


class Verbosity(IntEnum):
    QUIET = 0
    DEFAULT = 1
    VERBOSE = 2


_verbosity: Verbosity = Verbosity.DEFAULT


def get_verbosity() -> Verbosity:
    return _verbosity


def set_verbosity(v: Verbosity) -> None:
    global _verbosity
    _verbosity = v


# --- Step runner ---


def run_step(label: str, func: Callable[[], T], warn_if: Optional[Callable[[T], bool]] = None) -> T:
    """Run func with spinner, then print completion line.

    If the result indicates failure and ``warn_if(result)`` returns True,
    a yellow ``~`` warning icon is shown instead of the red ``✗``.
    """
    if _verbosity == Verbosity.QUIET:
        return func()

    with console.status(f"  {label}"):
        result = func()

    ok = not hasattr(result, "success") or result.success
    warn = not ok and warn_if is not None and warn_if(result)
    if ok:
        mark = "[green]✓[/green]"
    elif warn:
        mark = "[yellow]~[/yellow]"
    else:
        mark = "[red]✗[/red]"
    done_label = label.rstrip(". ")
    console.print(f"  {mark} {done_label}")

    if _verbosity >= Verbosity.VERBOSE and hasattr(result, "output") and result.output.strip():
        for line in result.output.strip().splitlines():
            console.print(f"    [dim]{line}[/dim]")

    return result


# --- Output helpers ---


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    console.print_json(json.dumps(data, default=str, indent=2))


def print_error(message: str) -> None:
    """Print an error message to stderr. Always prints."""
    error_console.print(f"[red]Error:[/red] {message}")


def print_warning(message: str) -> None:
    """Print a warning message. Silenced in QUIET."""
    if _verbosity >= Verbosity.DEFAULT:
        console.print(f"[yellow]Warning:[/yellow] {message}")


def print_success(message: str) -> None:
    """Print a success message. Silenced in QUIET."""
    if _verbosity >= Verbosity.DEFAULT:
        console.print(f"[green]{message}[/green]")


def print_info(message: str) -> None:
    """Print an info message. Silenced in QUIET."""
    if _verbosity >= Verbosity.DEFAULT:
        console.print(f"[blue]{message}[/blue]")


def print_verbose(message: str) -> None:
    """Print only in VERBOSE mode."""
    if _verbosity >= Verbosity.VERBOSE:
        console.print(f"[dim]{message}[/dim]")


# --- Tables ---


def create_table(title: str, columns: list[str]) -> Table:
    """Create a Rich table with the given title and columns."""
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    return table


def print_table(table: Table) -> None:
    """Print a Rich table."""
    console.print(table)


def print_domains_table(domains: list[dict]) -> None:
    """Print a table of domains."""
    if not domains:
        console.print("[dim]No domains found[/dim]")
        return

    table = Table(title="PeopleSoft Domains")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Path", style="dim")

    for domain in domains:
        status_style = "green" if domain.get("status") == "running" else "red"
        table.add_row(
            domain.get("name", "unknown"),
            domain.get("type", "unknown"),
            f"[{status_style}]{domain.get('status', 'unknown')}[/{status_style}]",
            str(domain.get("path", "")),
        )

    console.print(table)
