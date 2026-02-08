"""Output formatting utilities."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    console.print_json(json.dumps(data, default=str, indent=2))


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    error_console.print(f"[red]Error:[/red] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]Warning:[/yellow] {message}")


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]{message}[/green]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[blue]{message}[/blue]")


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
