"""Point d'entrée CLI interactif pour l'agent IA local avec mode Essaim (Swarm)."""

import argparse
import os
import sys
from dataclasses import dataclass

import ollama
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent import (
    DEFAULT_WORKERS,
    NUM_CTX,
    OLLAMA_URL,
    AgentLoop,
    ConversationContext,
    SwarmManager,
    WorkspaceState,
    build_system_prompt,
    get_installed_models,
    load_dotenv,
    select_default_model,
)
from tools import create_default_registry

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class SessionState:
    swarm_enabled: bool = True


def _read_prompt(session: object | None, active_dir: str) -> str:
    label = f"[{os.path.basename(active_dir) or active_dir}] > "
    if session is not None:
        return session.prompt(label).strip()
    return input(label).strip()


def _create_prompt_session() -> object | None:
    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession

        return PromptSession()
    except Exception:
        return None


def _print_banner(
    console: Console,
    model: str,
    installed: list[str],
    reachable: bool,
    workspace: WorkspaceState,
    tools_count: int,
    swarm_enabled: bool,
) -> None:
    status_line = (
        f"[green]Connecté[/green] ({len(installed)} modèle(s))"
        if reachable
        else "[red]Hors ligne[/red] — démarre Ollama (`ollama serve` ou l'application Ollama)"
    )
    swarm_line = (
        f"[green]ACTIF[/green] ({len(DEFAULT_WORKERS)} workers, zero-swap VRAM)"
        if swarm_enabled
        else "[dim]INACTIF[/dim]"
    )
    info = (
        f"[bold]Modèle :[/bold] {model}\n"
        f"[bold]Ollama :[/bold] {OLLAMA_URL} — {status_line}\n"
        f"[bold]Swarm :[/bold] {swarm_line}\n"
        f"[bold]Contexte :[/bold] {NUM_CTX} tokens | [bold]Outils actifs :[/bold] {tools_count}\n"
        f"[bold]Dossier :[/bold] {workspace.active_dir}\n"
        "[dim]Commandes : /help /model /swarm /cd /tools /debug /think /undo /clear /quit[/dim]"
    )
    console.print(Panel(info, title="Agent IA Local (Orchestrateur Swarm + Tool Calling)", border_style="cyan"))

    has_abliterated = any("huihui_ai/qwen3-abliterated:14b" in m for m in installed)
    if not has_abliterated:
        console.print(
            "[yellow]Astuce modèle non censuré (16 Go VRAM) :[/yellow] "
            "`ollama pull huihui_ai/qwen3-abliterated:14b`"
        )


def _print_swarm_table(console: Console, swarm: SwarmManager, swarm_enabled: bool) -> None:
    state_label = "ACTIF" if swarm_enabled else "INACTIF"
    table = Table(title=f"Workers Swarm ({state_label})")
    table.add_column("Rôle", style="magenta")
    table.add_column("Modèle")
    table.add_column("Outils autorisés")
    for name, profile in DEFAULT_WORKERS.items():
        active_tools = [t for t in profile.allowed_tools if swarm.base_registry.get_tool(t) is not None]
        model_label = swarm.get_model_for_role(name)
        suffix = " (hérité)" if swarm.role_models.get(name) is None else " (override)"
        table.add_row(name, f"{model_label}{suffix}", ", ".join(active_tools))
    console.print(table)


def _print_help(console: Console) -> None:
    table = Table(title="Commandes disponibles", show_header=True, header_style="bold cyan")
    table.add_column("Commande", style="bold")
    table.add_column("Action")
    commands = [
        ("/help", "Affiche cette aide"),
        ("/model [nom]", "Liste les modèles Ollama ou change le modèle orchestrateur"),
        ("/swarm [status|on|off]", "Affiche ou active/désactive le mode Essaim (Swarm)"),
        ("/swarm model <rôle> <modèle|inherit>", "Assigne un modèle spécifique à un worker"),
        ("/cd <chemin>", "Change le dossier de travail actif"),
        ("/tools", "Liste les outils actifs et leur description"),
        ("/debug", "Active/désactive les métriques détaillées (tok/s, contexte, args)"),
        ("/think", "Affiche/masque les blocs de réflexion <think>"),
        ("/undo", "Annule les modifications de fichiers de la session"),
        ("/clear", "Réinitialise l'historique de conversation"),
        ("/quit | exit", "Quitte l'agent"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    console.print(table)


def _handle_swarm_command(
    arg: str,
    console: Console,
    loop: AgentLoop,
    context: ConversationContext,
    workspace: WorkspaceState,
    swarm: SwarmManager,
    state: SessionState,
) -> None:
    subparts = arg.split()
    action = subparts[0].lower() if subparts else "status"
    if action == "status":
        _print_swarm_table(console, swarm, state.swarm_enabled)
    elif action == "on":
        state.swarm_enabled = True
        swarm.register_delegate_tool(loop.registry)
        context.set_system(build_system_prompt(workspace.active_dir, swarm_enabled=True))
        console.print("[green]Mode Swarm activé (`delegate_task` disponible).[/green]")
    elif action == "off":
        state.swarm_enabled = False
        loop.registry.unregister("delegate_task")
        context.set_system(build_system_prompt(workspace.active_dir, swarm_enabled=False))
        console.print("[yellow]Mode Swarm désactivé (`delegate_task` retiré).[/yellow]")
    elif action == "model" and len(subparts) == 3:
        console.print(swarm.set_role_model(subparts[1], subparts[2]))
    else:
        console.print("[yellow]Usage : /swarm [status|on|off] ou /swarm model <rôle> <modèle|inherit>[/yellow]")


def _handle_command(
    raw: str,
    console: Console,
    client: ollama.Client,
    loop: AgentLoop,
    context: ConversationContext,
    workspace: WorkspaceState,
    swarm: SwarmManager,
    state: SessionState,
) -> bool:
    """Traite une commande slash. Retourne True si l'agent doit quitter."""
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit", "exit", "quit"):
        return True
    if cmd == "/help":
        _print_help(console)
    elif cmd == "/swarm":
        _handle_swarm_command(arg, console, loop, context, workspace, swarm, state)
    elif cmd == "/model":
        installed, reachable = get_installed_models(client)
        if not arg:
            if not reachable:
                console.print("[red]Ollama inaccessible.[/red]")
                return False
            table = Table(title="Modèles Ollama installés")
            table.add_column("Modèle")
            table.add_column("Actif")
            for m in installed:
                table.add_row(m, "✅" if m == loop.model else "")
            console.print(table)
        else:
            loop.model = arg
            if reachable and arg not in installed:
                console.print(f"[yellow]Modèle changé vers '{arg}' (non détecté localement).[/yellow]")
            else:
                console.print(f"[green]Modèle actif : {arg}[/green]")
    elif cmd == "/cd":
        if not arg:
            console.print(f"Dossier actif : {workspace.active_dir}")
            return False
        target = workspace.resolve_path(arg.strip('"').strip("'"))
        if os.path.isdir(target):
            workspace.active_dir = target
            context.set_system(build_system_prompt(target, swarm_enabled=state.swarm_enabled))
            console.print(f"[green]Dossier actif : {target}[/green]")
        else:
            console.print(f"[red]Dossier introuvable : {target}[/red]")
    elif cmd == "/tools":
        table = Table(title="Outils actifs")
        table.add_column("Nom", style="cyan")
        table.add_column("Description")
        for tool in loop.registry.list_tools():
            table.add_row(tool.name, tool.description)
        console.print(table)
    elif cmd == "/debug":
        loop.debug = not loop.debug
        console.print(f"Mode debug : {'[green]ON[/green]' if loop.debug else '[dim]OFF[/dim]'}")
    elif cmd == "/think":
        loop.show_thinking = not loop.show_thinking
        console.print(f"Affichage réflexion : {'[green]ON[/green]' if loop.show_thinking else '[dim]OFF[/dim]'}")
    elif cmd == "/undo":
        console.print(workspace.undo())
    elif cmd == "/clear":
        context.clear()
        console.print("[green]Historique de conversation réinitialisé.[/green]")
    else:
        console.print(f"[yellow]Commande inconnue : {cmd}. Tape /help.[/yellow]")
    return False


def main() -> int:
    load_dotenv(os.path.join(BASE_DIR, ".env"))

    parser = argparse.ArgumentParser(description="Agent IA local avec Tool Calling natif Ollama.")
    parser.add_argument("--check", action="store_true", help="Affiche le diagnostic et quitte.")
    parser.add_argument("--model", help="Force un modèle Ollama spécifique.")
    parser.add_argument("--debug", action="store_true", help="Active le mode debug au démarrage.")
    args = parser.parse_args()

    console = Console()
    client = ollama.Client(host=OLLAMA_URL)
    selected_model, installed, reachable = select_default_model(client)
    if args.model:
        selected_model = args.model

    state = SessionState(swarm_enabled=True)
    workspace = WorkspaceState(BASE_DIR)
    registry = create_default_registry(workspace)
    context = ConversationContext(build_system_prompt(workspace.active_dir, swarm_enabled=state.swarm_enabled))
    loop = AgentLoop(
        client=client,
        model=selected_model,
        context=context,
        registry=registry,
        workspace=workspace,
        console=console,
        debug=args.debug,
    )
    swarm = SwarmManager(
        client=client,
        get_orchestrator_model=lambda: loop.model,
        base_registry=registry,
        workspace=workspace,
        console=console,
        get_debug=lambda: loop.debug,
        get_show_thinking=lambda: loop.show_thinking,
        num_ctx=NUM_CTX,
    )
    swarm.register_delegate_tool(registry)

    _print_banner(
        console,
        selected_model,
        installed,
        reachable,
        workspace,
        len(registry.list_tools()),
        state.swarm_enabled,
    )

    if args.check:
        table = Table(title="Outils enregistrés")
        table.add_column("Nom", style="cyan")
        table.add_column("Description")
        for t in registry.list_tools():
            table.add_row(t.name, t.description)
        console.print(table)
        _print_swarm_table(console, swarm, state.swarm_enabled)
        return 0

    prompt_session = _create_prompt_session()
    while True:
        try:
            user_input = _read_prompt(prompt_session, workspace.active_dir)
        except (EOFError, KeyboardInterrupt):
            console.print("\nAu revoir.")
            break

        if not user_input:
            continue
        if user_input.startswith("/") or user_input.lower() in ("exit", "quit"):
            if _handle_command(user_input, console, client, loop, context, workspace, swarm, state):
                break
            continue

        if not get_installed_models(client)[1]:
            console.print("[red]Impossible de contacter Ollama. Lance `ollama serve` puis réessaie.[/red]")
            continue

        loop.run_turn(user_input)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
