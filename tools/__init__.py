"""Registre des outils natifs pour Ollama."""

import os

from agent.context import WorkspaceState
from tools.filesystem import register_filesystem_tools
from tools.registry import ToolRegistry
from tools.shell import register_shell_tool
from tools.web import register_web_tool


def create_default_registry(workspace: WorkspaceState) -> ToolRegistry:
    """Crée et enregistre les outils de base (6 outils noyau + web_search si configuré)."""
    registry = ToolRegistry()
    register_filesystem_tools(registry, workspace)
    register_shell_tool(registry, workspace)
    if os.environ.get("TAVILY_API_KEY", "").strip():
        register_web_tool(registry)
    return registry


__all__ = ["ToolRegistry", "create_default_registry"]
