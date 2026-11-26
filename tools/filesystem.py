"""Outils système de fichiers sûrs (list_dir, read_file, grep_search, edit_file, write_file)."""

import ast
import difflib
import os
import re

from agent.context import WorkspaceState
from tools.registry import ToolRegistry

IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "legacy", ".pytest_cache", "dist", "build"}
TEXT_EXTS = {
    ".py", ".c", ".cpp", ".h", ".hpp", ".java", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".sql", ".json", ".yaml", ".yml", ".toml", ".md", ".txt",
    ".sh", ".ps1", ".bat", ".csv", ".ini", ".cfg", ".env", ".xml",
}


def _validate_and_write(workspace: WorkspaceState, abs_path: str, new_content: str, old_content: str | None) -> str:
    """Valide la syntaxe Python si applicable, sauvegarde pour /undo, écrit et retourne le diff."""
    if abs_path.endswith(".py"):
        try:
            ast.parse(new_content)
        except SyntaxError as exc:
            lines = new_content.splitlines()
            bad_line = lines[exc.lineno - 1] if exc.lineno and exc.lineno <= len(lines) else ""
            return (
                f"Erreur syntaxe Python ligne {exc.lineno} ({exc.msg}) : {bad_line}\n"
                "Écriture annulée : le fichier n'a pas été modifié."
            )

    workspace.backup_once(abs_path)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as fh:
        fh.write(new_content)

    name = os.path.basename(abs_path)
    if old_content is None:
        line_count = len(new_content.splitlines())
        return f"Fichier '{name}' créé/écrit ({line_count} lignes)."

    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            lineterm="",
            n=2,
        )
    )
    if not diff_lines:
        return f"Fichier '{name}' inchangé."
    preview = "\n".join(diff_lines[:40])
    if len(diff_lines) > 40:
        preview += "\n... (diff tronqué)"
    return f"Fichier '{name}' modifié :\n{preview}"


def _flexible_replace(content: str, old_text: str, new_text: str) -> tuple[str, bool]:
    """Remplace old_text exactement, ou en tolérant les espaces en fin de ligne."""
    if old_text in content:
        return content.replace(old_text, new_text, 1), True

    content_lines = content.splitlines()
    target_lines = [line.rstrip() for line in old_text.strip("\r\n").splitlines()]
    if not target_lines:
        return content, False

    width = len(target_lines)
    for i in range(len(content_lines) - width + 1):
        window = [line.rstrip() for line in content_lines[i : i + width]]
        if window == target_lines:
            replacement = new_text.strip("\r\n").splitlines()
            updated = content_lines[:i] + replacement + content_lines[i + width :]
            trailing_nl = "\n" if content.endswith("\n") else ""
            return "\n".join(updated) + trailing_nl, True
    return content, False


def register_filesystem_tools(registry: ToolRegistry, workspace: WorkspaceState) -> None:
    """Enregistre les 5 outils fichiers liés au WorkspaceState."""

    def list_dir(path: str = ".") -> str:
        target = workspace.resolve_path(path)
        if not os.path.exists(target):
            return f"Erreur : le chemin '{target}' n'existe pas."
        if os.path.isfile(target):
            size = os.path.getsize(target)
            return f"'{target}' est un fichier ({size} octets). Utilise `read_file`."

        entries: list[str] = []
        for item in sorted(os.listdir(target)):
            if item in IGNORED_DIRS or (item.startswith(".") and item != ".env.example"):
                continue
            full = os.path.join(target, item)
            if os.path.isdir(full):
                entries.append(f"[DIR]  {item}/")
            else:
                size_kb = round(os.path.getsize(full) / 1024, 1)
                entries.append(f"[FILE] {item} ({size_kb} KB)")
        if not entries:
            return f"Dossier '{target}' vide."
        return f"Contenu de {target} ({len(entries)} éléments) :\n" + "\n".join(entries[:80])

    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
        if not path or not path.strip():
            return "Erreur : le paramètre 'path' est requis."
        abs_path = workspace.resolve_path(path)
        if not os.path.isfile(abs_path):
            return f"Erreur : fichier '{abs_path}' introuvable."
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        if not lines:
            return f"Fichier '{os.path.basename(abs_path)}' vide (0 ligne)."
        s = max(1, int(start_line))
        e = min(len(lines), max(s, int(end_line)))
        numbered = [f"{i:4d} | {lines[i - 1]}" for i in range(s, e + 1)]
        return f"{os.path.basename(abs_path)} (lignes {s}-{e}/{len(lines)}) :\n" + "\n".join(numbered)

    def grep_search(pattern: str, path: str = ".") -> str:
        if not pattern:
            return "Erreur : le paramètre 'pattern' est requis."
        target = workspace.resolve_path(path)
        if not os.path.exists(target):
            return f"Erreur : chemin '{target}' introuvable."
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        matches: list[str] = []
        files_to_scan: list[str] = []
        if os.path.isfile(target):
            files_to_scan.append(target)
        else:
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                for fname in sorted(files):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in TEXT_EXTS or ext == "":
                        files_to_scan.append(os.path.join(root, fname))

        for fp in files_to_scan:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex.search(line):
                            rel = os.path.relpath(fp, workspace.active_dir)
                            matches.append(f"{rel}:{lineno}: {line.strip()[:120]}")
                            if len(matches) >= 40:
                                break
            except Exception:
                continue
            if len(matches) >= 40:
                break

        if not matches:
            return f"Aucune occurrence de '{pattern}' dans {target}."
        return f"Résultats ({len(matches)}) :\n" + "\n".join(matches)

    def edit_file(path: str, old_text: str, new_text: str) -> str:
        if not path or not old_text:
            return "Erreur : 'path' et 'old_text' sont requis."
        abs_path = workspace.resolve_path(path)
        if not os.path.isfile(abs_path):
            return f"Erreur : fichier '{abs_path}' introuvable."
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            old_content = fh.read()
        updated, ok = _flexible_replace(old_content, old_text, new_text)
        if not ok:
            return (
                f"Erreur : le bloc 'old_text' est introuvable dans {os.path.basename(abs_path)}. "
                "Lis d'abord le fichier avec `read_file` pour copier les lignes exactes."
            )
        return _validate_and_write(workspace, abs_path, updated, old_content)

    def write_file(path: str, content: str) -> str:
        if not path or not path.strip():
            return "Erreur : le paramètre 'path' est requis."
        abs_path = workspace.resolve_path(path)
        old_content = None
        if os.path.isfile(abs_path):
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                old_content = fh.read()
        return _validate_and_write(workspace, abs_path, content, old_content)

    registry.register(
        name="list_dir",
        description="Liste les fichiers et dossiers d'un répertoire.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin relatif ou absolu (défaut: '.')."},
            },
        },
        handler=list_dir,
    )

    registry.register(
        name="read_file",
        description="Lit les lignes d'un fichier texte ou code avec numéros de lignes.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin du fichier à lire."},
                "start_line": {"type": "integer", "description": "Ligne de début (défaut: 1)."},
                "end_line": {"type": "integer", "description": "Ligne de fin (défaut: 200)."},
            },
            "required": ["path"],
        },
        handler=read_file,
    )

    registry.register(
        name="grep_search",
        description="Recherche un motif regex dans un fichier ou dossier du projet.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Motif regex ou texte à rechercher."},
                "path": {"type": "string", "description": "Fichier ou sous-dossier cible (défaut: '.')."},
            },
            "required": ["pattern"],
        },
        handler=grep_search,
    )

    registry.register(
        name="edit_file",
        description="Remplace un bloc de texte exact dans un fichier existant (avec vérification syntaxe Python).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin du fichier à modifier."},
                "old_text": {"type": "string", "description": "Bloc exact actuel à remplacer."},
                "new_text": {"type": "string", "description": "Nouveau bloc de remplacement."},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=edit_file,
    )

    registry.register(
        name="write_file",
        description="Crée ou remplace entièrement un fichier (avec vérification syntaxe Python).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin du fichier à écrire."},
                "content": {"type": "string", "description": "Contenu complet du fichier."},
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    )
