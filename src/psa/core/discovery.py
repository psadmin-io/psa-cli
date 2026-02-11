"""Shared discovery logic with type filtering."""

from __future__ import annotations

from typing import Optional

import typer

from psa.core.config import PsaConfig, get_config
from psa.core.domain import DomainDiscovery, DomainInfo
from psa.core.output import print_error


def run_discovery(
    config: PsaConfig,
    domain_type: Optional[str] = None,
) -> list[DomainInfo]:
    """Run domain discovery with optional type filter.

    Raises typer.Exit(1) on invalid type or discovery error.
    """
    discovery = DomainDiscovery(config)
    try:
        if domain_type:
            domain_type = domain_type.lower()
            if domain_type == "app":
                return discovery.discover_appserver_domains()
            elif domain_type == "prcs":
                return discovery.discover_prcs_domains()
            elif domain_type == "pia":
                return discovery.discover_pia_domains()
            else:
                print_error(f"Unknown domain type: {domain_type}")
                print_error("Valid types: app, prcs, pia")
                raise typer.Exit(1)
        else:
            return discovery.discover_all()
    except typer.Exit:
        raise
    except PermissionError as e:
        print_error(f"Permission denied accessing domain paths: {e}")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Discovery failed: {e}")
        raise typer.Exit(1)
