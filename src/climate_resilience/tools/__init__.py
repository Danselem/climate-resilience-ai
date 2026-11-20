"""Typed analytical tools over the mart.

The registry is explicit: a caller can import a tool, but there is no dynamic
lookup that lets a model invent one.
"""

from __future__ import annotations

from .mart_tools import (
    coverage,
    explain,
    get_indicator,
    rank_scopes,
    resolve_scope,
)
from .models import Available, ScopeRef, ToolOutput

__all__ = [
    "Available",
    "ScopeRef",
    "ToolOutput",
    "coverage",
    "explain",
    "get_indicator",
    "rank_scopes",
    "resolve_scope",
]
