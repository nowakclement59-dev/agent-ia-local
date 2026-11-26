import sys
import io
import traceback
from contextlib import redirect_stdout, redirect_stderr

SKILL_PROMPT = '- `{"action": "python_repl", "code": "import fitz; print(fitz.__doc__)"}` (Skill REPL : exécute du code Python à la volée dans une session persistante pour tester une fonction ou inspecter un objet)'

_REPL_GLOBALS = {}

def execute(data: dict) -> tuple[str, bool]:
    code = data.get("code", "").strip()
    if not code:
        return "Erreur : Le champ 'code' est vide.", True

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            compiled_code = compile(code, "<agent_repl>", "exec")
            exec(compiled_code, _REPL_GLOBALS)
            
        out = stdout_capture.getvalue()
        err = stderr_capture.getvalue()
        
        result = ""
        if out:
            result += f"STDOUT:\n{out}"
        if err:
            result += f"\nSTDERR:\n{err}"
        if not result:
            result = "Code exécuté avec succès (Aucune sortie imprimée)."
            
        return f"🐍 REPL Output :\n{result.strip()}", (err != "")
    except Exception:
        error_msg = traceback.format_exc()
        return f"❌ Erreur REPL :\n{error_msg}", True
