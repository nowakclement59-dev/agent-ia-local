"""Outil d'exécution de commandes PowerShell avec timeout et nettoyage de processus."""

import subprocess

from agent.context import WorkspaceState
from tools.registry import ToolRegistry


def register_shell_tool(registry: ToolRegistry, workspace: WorkspaceState) -> None:
    """Enregistre l'outil `run_command` dans le registre."""

    def run_command(command: str, timeout: int = 30) -> str:
        cmd = (command or "").strip()
        if not cmd:
            return "Erreur : le paramètre 'command' est vide."
        safe_timeout = max(1, min(120, int(timeout or 30)))

        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", cmd],
            cwd=workspace.active_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        try:
            stdout, stderr = proc.communicate(timeout=safe_timeout)
            combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
            status = f"Code retour : {proc.returncode}"
            return f"{status}\n{combined}" if combined else f"{status} (aucune sortie)."
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            return f"Timeout dépassé ({safe_timeout}s) : processus arrêté."

    registry.register(
        name="run_command",
        description="Exécute une commande PowerShell dans le dossier actif (tests, git, outils CLI, Python).",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Commande PowerShell à exécuter."},
                "timeout": {"type": "integer", "description": "Timeout en secondes (défaut: 30, max: 120)."},
            },
            "required": ["command"],
        },
        handler=run_command,
    )
