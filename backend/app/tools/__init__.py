"""Реестр тулов агента."""
from __future__ import annotations

from . import events, fuel, geocode, lodging, places, routing, transport, weather, wiki
from .base import Tool, ToolContext

ALL_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        geocode.TOOL, places.TOOL, weather.TOOL, routing.TOOL, fuel.TOOL,
        lodging.TOOL, transport.TOOL, events.TOOL, wiki.TOOL,
    )
}

__all__ = ["ALL_TOOLS", "Tool", "ToolContext"]
