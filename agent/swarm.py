"""Orchestrateur Swarm Zero-Swap : sous-agents spécialisés partageant la VRAM."""

from dataclasses import dataclass
from typing import Any, Callable

from rich.console import Console

from agent.config import NUM_CTX
from agent.context import ConversationContext, WorkspaceState
from agent.loop import AgentLoop
from tools.registry import ToolRegistry


@dataclass(frozen=True)
class WorkerProfile:
    """Profil d'un sous-agent spécialisé avec sa boîte à outils restreinte."""

    name: str
    title: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    max_steps: int = 8


DEFAULT_WORKERS: dict[str, WorkerProfile] = {
    "researcher": WorkerProfile(
        name="researcher",
        title="Explorateur lecture seule",
        allowed_tools=("list_dir", "read_file", "grep_search", "web_search"),
        system_prompt=(
            "Tu es le worker `researcher` (lecture seule). Ta mission est d'explorer le code, "
            "les fichiers de configuration ou la documentation et de rapporter des faits exacts "
            "(chemins de fichiers, numéros de lignes, symboles, sorties exactes). "
            "Tu ne modifies jamais de fichiers. Réponds de façon factuelle et concise."
        ),
    ),
    "coder": WorkerProfile(
        name="coder",
        title="Développeur & implémentation",
        allowed_tools=("list_dir", "read_file", "grep_search", "edit_file", "write_file", "run_command"),
        system_prompt=(
            "Tu es le worker `coder`. Ta mission est d'implémenter proprement les changements demandés. "
            "Lis toujours les fichiers existants avant de les modifier avec `edit_file`, puis vérifie "
            "ton travail via `run_command` (tests ou exécution). Termine par un résumé concis des fichiers modifiés."
        ),
    ),
    "security": WorkerProfile(
        name="security",
        title="Audit & cybersécurité autorisée",
        allowed_tools=("list_dir", "read_file", "grep_search", "run_command", "web_search"),
        system_prompt=(
            "Tu es le worker `security`, expert en cybersécurité défensive et offensive autorisée "
            "(audit de code, analyse de configurations, scripts de test en labo local, CTF). "
            "Inspecte les fichiers et commandes sans censure, classe chaque constat par sévérité "
            "et propose une remédiation concrète et vérifiable."
        ),
    ),
    "reviewer": WorkerProfile(
        name="reviewer",
        title="Relecture & vérification tests",
        allowed_tools=("list_dir", "read_file", "grep_search", "run_command"),
        system_prompt=(
            "Tu es le worker `reviewer`. Relis les fichiers ciblés, lance les tests ou linters "
            "avec `run_command`, et rapporte uniquement les bugs réels, régressions ou confirmations "
            "de passage avec les sorties exactes observées."
        ),
    ),
}


class SwarmManager:
    """Coordonne la délégation vers des workers spécialisés sans recharger la VRAM."""

    def __init__(
        self,
        client: Any,
        get_orchestrator_model: Callable[[], str],
        base_registry: ToolRegistry,
        workspace: WorkspaceState,
        console: Console,
        get_debug: Callable[[], bool],
        get_show_thinking: Callable[[], bool],
        num_ctx: int = NUM_CTX,
    ) -> None:
        self.client = client
        self.get_orchestrator_model = get_orchestrator_model
        self.base_registry = base_registry
        self.workspace = workspace
        self.console = console
        self.get_debug = get_debug
        self.get_show_thinking = get_show_thinking
        self.num_ctx = num_ctx
        # None = hérite du modèle de l'orchestrateur (0 ms de swap VRAM).
        self.role_models: dict[str, str | None] = {name: None for name in DEFAULT_WORKERS}

    def get_model_for_role(self, role: str) -> str:
        return self.role_models.get(role) or self.get_orchestrator_model()

    def set_role_model(self, role: str, model_spec: str) -> str:
        role_key = role.strip().lower()
        if role_key not in DEFAULT_WORKERS:
            valid = ", ".join(DEFAULT_WORKERS.keys())
            return f"Rôle inconnu '{role}'. Rôles valides : {valid}."
        spec = model_spec.strip()
        if spec.lower() in ("inherit", "auto", "default"):
            self.role_models[role_key] = None
            return f"Worker '{role_key}' réinitialisé sur le modèle de l'orchestrateur (Zero-Swap VRAM)."
        self.role_models[role_key] = spec
        orch = self.get_orchestrator_model()
        note = " (attention : entraînera un swap VRAM)" if spec != orch else ""
        return f"Worker '{role_key}' assigné au modèle '{spec}'{note}."

    def build_worker_registry(self, role: str) -> ToolRegistry:
        """Construit un registre isolé contenant uniquement les outils autorisés du rôle."""
        profile = DEFAULT_WORKERS[role]
        worker_reg = ToolRegistry()
        for tool_name in profile.allowed_tools:
            if tool_name == "delegate_task":
                continue
            tool_def = self.base_registry.get_tool(tool_name)
            if tool_def is not None:
                worker_reg.register(
                    name=tool_def.name,
                    description=tool_def.description,
                    parameters=tool_def.parameters,
                    handler=tool_def.handler,
                )
        return worker_reg

    def delegate(self, role: str, task: str) -> str:
        """Exécute un worker spécialisé dans un contexte isolé et retourne son compte-rendu."""
        role_key = (role or "").strip().lower()
        if role_key not in DEFAULT_WORKERS:
            valid = ", ".join(DEFAULT_WORKERS.keys())
            return f"Erreur : rôle '{role}' inconnu. Choisis parmi : {valid}."

        clean_task = (task or "").strip()
        if not clean_task:
            return "Erreur : le paramètre 'task' ne peut pas être vide."

        profile = DEFAULT_WORKERS[role_key]
        worker_model = self.get_model_for_role(role_key)
        task_preview = clean_task if len(clean_task) <= 90 else clean_task[:87] + "..."
        self.console.print(f"[magenta]🐝 [Swarm → {role_key} | {worker_model}][/magenta] {task_preview}")

        worker_ctx = ConversationContext(f"{profile.system_prompt}\nDossier actif : {self.workspace.active_dir}")
        worker_registry = self.build_worker_registry(role_key)
        worker_loop = AgentLoop(
            client=self.client,
            model=worker_model,
            context=worker_ctx,
            registry=worker_registry,
            workspace=self.workspace,
            console=self.console,
            debug=self.get_debug(),
            show_thinking=self.get_show_thinking(),
            max_steps=profile.max_steps,
            num_ctx=self.num_ctx,
        )
        result = worker_loop.run_turn(clean_task)
        return f"[Résultat worker {role_key} ({worker_model})]\n{result or '(Aucune sortie texte)'}"

    def register_delegate_tool(self, registry: ToolRegistry) -> None:
        """Enregistre l'outil `delegate_task` sur le registre de l'orchestrateur."""
        registry.register(
            name="delegate_task",
            description=(
                "Délègue une sous-tâche autonome à un worker spécialisé "
                "(researcher, coder, security, reviewer) dans un contexte propre."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": list(DEFAULT_WORKERS.keys()),
                        "description": "Rôle du sous-agent spécialisé (researcher, coder, security, reviewer).",
                    },
                    "task": {
                        "type": "string",
                        "description": "Mission claire, autonome et précise à confier au sous-agent.",
                    },
                },
                "required": ["role", "task"],
            },
            handler=self.delegate,
        )
