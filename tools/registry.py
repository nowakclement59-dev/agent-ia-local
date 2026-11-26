"""Registre d'outils générant le schéma natif Ollama et gérant la troncature."""

from dataclasses import dataclass
from typing import Any, Callable


def smart_truncate(text: str, max_chars: int = 3500) -> str:
    """Conserve le début (2200 car.) et la fin (1100 car.) pour préserver erreurs et résumés."""
    if len(text) <= max_chars:
        return text
    head = min(2200, int(max_chars * 0.63))
    tail = max(0, max_chars - head - 60)
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n... [{omitted} caractères omis] ...\n\n{text[-tail:]}"


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., str]


class ToolRegistry:
    """Stocke les outils enregistrés, exporte le format Ollama et exécute les appels."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., str],
    ) -> None:
        self._tools[name] = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get_tool(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDef]:
        return list(self._tools.values())

    def get_ollama_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools.keys()))
            return f"Erreur : outil '{name}' inconnu. Outils disponibles : {available}."
        try:
            raw_output = tool.handler(**(arguments or {}))
            return smart_truncate(str(raw_output))
        except TypeError as exc:
            return f"Erreur d'arguments pour '{name}' : {exc}"
        except Exception as exc:
            return f"Erreur lors de l'exécution de '{name}' : {exc}"
