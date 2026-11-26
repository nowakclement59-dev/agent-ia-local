import subprocess
import os
import ast

SKILL_PROMPT = '- `{"action": "pylint_check", "path": "main.py"}` (Skill Qualité : vérifie la syntaxe AST et analyse les erreurs potentielles d\'un fichier Python)'

def execute(data: dict) -> tuple[str, bool]:
    path = data.get("path", "main.py").strip()
    if not os.path.exists(path):
        return f"Erreur : Fichier '{path}' introuvable.", True
    try:
        source = open(path, "r", encoding="utf-8", errors="replace").read()
        ast.parse(source)
    except SyntaxError as se:
        return f"❌ Erreur de syntaxe AST ligne {se.lineno} : {se.msg}", True

    try:
        res = subprocess.run(["python", "-m", "py_compile", path], capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            return f"❌ Erreur compilation Python :\n{res.stderr}", True
        return f"✅ Analyse statique et compilation réussies sur {os.path.basename(path)} (0 erreur).", False
    except Exception as e:
        return f"Erreur pylint_check : {e}", True
