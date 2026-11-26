"""Boucle ReAct avec Tool Calling natif d'Ollama, streaming et anti-boucle."""

import json
import time
from typing import Any

from rich.console import Console

from agent.config import MAX_STEPS, NUM_CTX, NUM_PREDICT, REPEAT_PENALTY, TEMPERATURE
from agent.context import ConversationContext, WorkspaceState
from tools.registry import ToolRegistry


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Lit un attribut sur un objet Pydantic ou une clé sur un dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_tool_call(tc: Any) -> dict[str, Any]:
    """Convertit un ToolCall Ollama (objet ou dict) en dict JSON-sérialisable."""
    fn = _get_field(tc, "function", {})
    name = str(_get_field(fn, "name", "") or "")
    raw_args = _get_field(fn, "arguments", {})
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {}
    elif isinstance(raw_args, dict):
        args = dict(raw_args)
    else:
        args = dict(raw_args or {})
    return {"function": {"name": name, "arguments": args}}


class AgentLoop:
    """Exécute la boucle conversation + appels d'outils natifs."""

    def __init__(
        self,
        client: Any,
        model: str,
        context: ConversationContext,
        registry: ToolRegistry,
        workspace: WorkspaceState,
        console: Console | None = None,
        debug: bool = False,
        show_thinking: bool = True,
        max_steps: int = MAX_STEPS,
        num_ctx: int = NUM_CTX,
    ) -> None:
        self.client = client
        self.model = model
        self.context = context
        self.registry = registry
        self.workspace = workspace
        self.console = console or Console()
        self.debug = debug
        self.show_thinking = show_thinking
        self.max_steps = max_steps
        self.num_ctx = num_ctx
        self.last_stats: dict[str, Any] = {}

    def _stream_chat(self, tools: list[dict[str, Any]]) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
        """Appelle Ollama en streaming et affiche la réponse / réflexion en direct."""
        options = {
            "temperature": TEMPERATURE,
            "repeat_penalty": REPEAT_PENALTY,
            "num_ctx": self.num_ctx,
            "num_predict": NUM_PREDICT,
        }
        stream = self.client.chat(
            model=self.model,
            messages=self.context.messages,
            tools=tools,
            stream=True,
            keep_alive="30m",
            options=options,
        )

        content_parts: list[str] = []
        thinking_parts: list[str] = []
        collected_calls: list[dict[str, Any]] = []
        stats: dict[str, Any] = {}

        in_inline_think = False
        think_header_printed = False
        answer_header_printed = False
        t0 = time.perf_counter()

        for chunk in stream:
            msg = _get_field(chunk, "message", {})
            think_delta = str(_get_field(msg, "thinking", "") or "")
            content_delta = str(_get_field(msg, "content", "") or "")
            raw_tcs = _get_field(msg, "tool_calls", None) or []

            if think_delta:
                thinking_parts.append(think_delta)
                if self.show_thinking:
                    if not think_header_printed:
                        self.console.print("[dim]💭 Réflexion :[/dim] ", end="")
                        think_header_printed = True
                    self.console.print(think_delta, style="dim italic", end="", markup=False, highlight=False)

            if content_delta:
                # Gestion des balises inline <think>...</think> si le modèle les émet dans content.
                pending = content_delta
                while pending:
                    if not in_inline_think:
                        idx = pending.find("<think>")
                        if idx == -1:
                            if think_header_printed and not answer_header_printed:
                                self.console.print()
                                answer_header_printed = True
                            content_parts.append(pending)
                            self.console.print(pending, end="", markup=False, highlight=False)
                            pending = ""
                        else:
                            before = pending[:idx]
                            if before:
                                content_parts.append(before)
                                self.console.print(before, end="", markup=False, highlight=False)
                            in_inline_think = True
                            pending = pending[idx + len("<think>"):]
                    else:
                        idx = pending.find("</think>")
                        if idx == -1:
                            thinking_parts.append(pending)
                            if self.show_thinking:
                                if not think_header_printed:
                                    self.console.print("[dim]💭 Réflexion :[/dim] ", end="")
                                    think_header_printed = True
                                self.console.print(pending, style="dim italic", end="", markup=False, highlight=False)
                            pending = ""
                        else:
                            chunk_t = pending[:idx]
                            if chunk_t:
                                thinking_parts.append(chunk_t)
                                if self.show_thinking:
                                    if not think_header_printed:
                                        self.console.print("[dim]💭 Réflexion :[/dim] ", end="")
                                        think_header_printed = True
                                    self.console.print(chunk_t, style="dim italic", end="", markup=False, highlight=False)
                            in_inline_think = False
                            if think_header_printed:
                                self.console.print()
                                answer_header_printed = True
                            pending = pending[idx + len("</think>"):]

            for tc in raw_tcs:
                collected_calls.append(_normalize_tool_call(tc))

            if _get_field(chunk, "done", False):
                eval_count = int(_get_field(chunk, "eval_count", 0) or 0)
                prompt_count = int(_get_field(chunk, "prompt_eval_count", 0) or 0)
                eval_ns = int(_get_field(chunk, "eval_duration", 0) or 0)
                elapsed = eval_ns / 1e9 if eval_ns > 0 else max(0.001, time.perf_counter() - t0)
                stats = {
                    "eval_count": eval_count,
                    "prompt_eval_count": prompt_count,
                    "tok_per_sec": round(eval_count / elapsed, 1) if eval_count else 0.0,
                    "elapsed_s": round(elapsed, 2),
                }

        if content_parts or (think_header_printed and not answer_header_printed):
            self.console.print()

        return "".join(content_parts).strip(), "".join(thinking_parts).strip(), collected_calls, stats

    def _print_debug_stats(self, step: int, stats: dict[str, Any]) -> None:
        if not self.debug:
            return
        est_ctx = self.context.estimate_tokens()
        pct = round((est_ctx / max(1, self.num_ctx)) * 100, 1)
        tok_s = stats.get("tok_per_sec", 0.0)
        ev = stats.get("eval_count", 0)
        pr = stats.get("prompt_eval_count", 0)
        self.console.print(
            f"[dim][debug] step={step} | prompt={pr} tok | gen={ev} tok ({tok_s} tok/s) | ctx≈{est_ctx}/{self.num_ctx} ({pct}%)[/dim]"
        )

    def run_turn(self, user_input: str) -> str:
        """Exécute un tour utilisateur complet (jusqu'à la réponse finale ou max_steps)."""
        self.context.add_user(user_input)
        self.context.prune_if_needed(int(self.num_ctx * 0.8))

        call_counts: dict[str, int] = {}
        tools_schema = self.registry.get_ollama_tools()
        final_text = ""

        try:
            for step in range(1, self.max_steps + 1):
                content, _thinking, tool_calls, stats = self._stream_chat(tools_schema)
                self.last_stats = stats
                self._print_debug_stats(step, stats)

                if not tool_calls:
                    self.context.add_assistant(content)
                    final_text = content
                    break

                self.context.add_assistant(content, tool_calls=tool_calls)

                force_finalize = False
                for tc in tool_calls:
                    fn = tc["function"]
                    name = fn["name"]
                    args = fn["arguments"]
                    sig = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                    call_counts[sig] = call_counts.get(sig, 0) + 1
                    count = call_counts[sig]

                    if count >= 3:
                        self.console.print(f"[yellow]🛑 Anti-boucle : appel répété 3 fois pour {name}, synthèse forcée.[/yellow]")
                        self.context.add_tool(
                            name,
                            f"Arrêt anti-boucle : '{name}' a déjà été appelé {count} fois avec ces paramètres identiques.",
                        )
                        force_finalize = True
                        continue

                    if count == 2:
                        self.console.print(f"[yellow]⚠️ Appel identique intercepté ({name}) — demande de changement d'approche.[/yellow]")
                        self.context.add_tool(
                            name,
                            f"Tu viens déjà d'appeler '{name}' avec exactement ces mêmes paramètres. "
                            "Ne répète pas cet appel : change de paramètres, essaie un autre outil, ou réponds à l'utilisateur.",
                        )
                        continue

                    args_preview = json.dumps(args, ensure_ascii=False)
                    if not self.debug and len(args_preview) > 100:
                        args_preview = args_preview[:97] + "..."
                    self.console.print(f"[cyan]🔧 {name}[/cyan]([dim]{args_preview}[/dim])")

                    result = self.registry.execute(name, args)
                    if self.debug:
                        preview = result[:300].replace("\n", " ")
                        self.console.print(f"[dim]   ↳ {preview}[/dim]")
                    self.context.add_tool(name, result)

                self.context.prune_if_needed(int(self.num_ctx * 0.85))

                if force_finalize or step == self.max_steps:
                    if step == self.max_steps and not force_finalize:
                        self.console.print(f"[yellow]⏱️ Limite de {self.max_steps} étapes atteinte — synthèse finale.[/yellow]")
                    self.context.add_user(
                        "Fais maintenant une synthèse claire et honnête pour l'utilisateur de ce qui a été fait, "
                        "trouvé ou bloqué, sans appeler d'outil."
                    )
                    summary, _, _, sum_stats = self._stream_chat(tools=[])
                    self.last_stats = sum_stats
                    self._print_debug_stats(step + 1, sum_stats)
                    self.context.add_assistant(summary)
                    final_text = summary
                    break

        except KeyboardInterrupt:
            self.console.print("\n[yellow]⏹️ Génération interrompue par l'utilisateur.[/yellow]")
            # Nettoie un éventuel assistant(tool_calls) orphelin sans réponse tool.
            if self.context.messages and self.context.messages[-1].get("tool_calls"):
                self.context.messages.pop()

        return final_text
