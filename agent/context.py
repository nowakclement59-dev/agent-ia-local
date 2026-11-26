"""Gestion de l'état de l'espace de travail (undo) et du contexte conversationnel."""

import os
from typing import Any


class WorkspaceState:
    """Suit le répertoire actif et sauvegarde les fichiers modifiés pour /undo."""

    def __init__(self, active_dir: str | None = None) -> None:
        self.active_dir = os.path.abspath(active_dir or os.getcwd())
        # None signifie que le fichier n'existait pas avant écriture (/undo le supprimera).
        self.file_backups: dict[str, str | None] = {}

    def resolve_path(self, path: str) -> str:
        """Résout un chemin relatif par rapport au dossier de travail actif."""
        cleaned = (path or ".").strip()
        if os.path.isabs(cleaned):
            return os.path.abspath(cleaned)
        return os.path.abspath(os.path.join(self.active_dir, cleaned))

    def backup_once(self, path: str) -> None:
        """Sauvegarde l'état initial d'un fichier une seule fois par session."""
        abs_path = self.resolve_path(path)
        if abs_path in self.file_backups:
            return
        if os.path.exists(abs_path) and os.path.isfile(abs_path):
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                self.file_backups[abs_path] = fh.read()
        else:
            self.file_backups[abs_path] = None

    def undo(self) -> str:
        """Restaure ou supprime les fichiers modifiés durant la session."""
        if not self.file_backups:
            return "Aucune modification à annuler."
        actions: list[str] = []
        for abs_path, previous in self.file_backups.items():
            name = os.path.basename(abs_path)
            if previous is None:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                    actions.append(f"supprimé {name}")
            else:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(previous)
                actions.append(f"restauré {name}")
        self.file_backups.clear()
        return "Rollback effectué : " + (", ".join(actions) if actions else "rien à restaurer.")


class ConversationContext:
    """Maintient l'historique des messages et élague proprement selon le budget tokens."""

    def __init__(self, system_prompt: str = "") -> None:
        self.messages: list[dict[str, Any]] = []
        if system_prompt:
            self.set_system(system_prompt)

    def set_system(self, prompt: str) -> None:
        """Définit ou met à jour le message système en position 0."""
        sys_msg = {"role": "system", "content": prompt}
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = sys_msg
        else:
            self.messages.insert(0, sys_msg)

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: str, tool_calls: list[dict[str, Any]] | None = None) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool(self, tool_name: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_name": tool_name, "content": content})

    def clear(self) -> None:
        """Vide l'historique tout en conservant le prompt système."""
        if self.messages and self.messages[0].get("role") == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []

    def estimate_tokens(self) -> int:
        """Estime le nombre de tokens (~3.5 caractères par token)."""
        total_chars = 0
        for msg in self.messages:
            total_chars += len(str(msg.get("content") or ""))
            if msg.get("tool_calls"):
                total_chars += len(str(msg["tool_calls"]))
        return max(1, int(total_chars / 3.5))

    @staticmethod
    def _compact_text(text: str, head: int = 300, tail: int = 200) -> str:
        if len(text) <= head + tail + 40:
            return text
        omitted = len(text) - head - tail
        return f"{text[:head]}\n... [{omitted} caractères compactés] ...\n{text[-tail:]}"

    def prune_if_needed(self, max_tokens: int) -> None:
        """Réduit l'historique sans jamais casser les paires assistant(tool_calls)->tool."""
        if self.estimate_tokens() <= max_tokens:
            return

        # 1. Compacter les anciens résultats d'outils (en préservant les 4 derniers messages).
        protected_start = max(1, len(self.messages) - 4)
        for idx in range(1, protected_start):
            if self.messages[idx].get("role") == "tool":
                self.messages[idx]["content"] = self._compact_text(
                    str(self.messages[idx].get("content") or "")
                )

        if self.estimate_tokens() <= max_tokens:
            return

        # 2. Supprimer les tours complets les plus anciens (d'un message user au suivant).
        has_system = bool(self.messages and self.messages[0].get("role") == "system")
        start_idx = 1 if has_system else 0

        while self.estimate_tokens() > max_tokens and len(self.messages) > start_idx + 1:
            # Trouver la fin du premier tour commençant à start_idx
            next_user = None
            for i in range(start_idx + 1, len(self.messages)):
                if self.messages[i].get("role") == "user":
                    next_user = i
                    break
            if next_user is None:
                break
            del self.messages[start_idx:next_user]

        # Sécurité : ne jamais laisser un message 'tool' orphelin juste après le système.
        while len(self.messages) > start_idx and self.messages[start_idx].get("role") == "tool":
            del self.messages[start_idx]
