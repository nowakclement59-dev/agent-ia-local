"""Configuration matérielle, sélection de modèle et prompt système de l'agent."""

import os
from typing import Any

def _resolve_ollama_url() -> str:
    raw = os.environ.get("AGENT_OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    raw = raw.strip()
    if raw.startswith("0.0.0.0"):
        raw = raw.replace("0.0.0.0", "127.0.0.1", 1)
    if "://" not in raw:
        raw = f"http://{raw}"
    if raw.rstrip("/") in ("http://127.0.0.1", "http://localhost"):
        raw = f"{raw.rstrip('/')}:11434"
    return raw


OLLAMA_URL = _resolve_ollama_url()
NUM_CTX = int(os.environ.get("AGENT_NUM_CTX", "16384"))
TEMPERATURE = 0.2
REPEAT_PENALTY = 1.05
NUM_PREDICT = 4096
MAX_STEPS = 12

PREFERRED_MODELS = [
    "huihui_ai/qwen3-abliterated:14b-v2",
    "huihui_ai/qwen3-abliterated:14b",
    "qwen3:14b",
    "hermes3:8b",
    "qwen2.5-coder:14b",
    "llama3.1:latest",
]


def load_dotenv(path: str = ".env") -> dict[str, str]:
    """Charge un fichier .env simple dans os.environ sans dépendance externe."""
    loaded: dict[str, str] = {}
    if not os.path.isfile(path):
        return loaded
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded[key] = value
    return loaded


def get_installed_models(client: Any) -> tuple[list[str], bool]:
    """Retourne (liste_des_modèles, ollama_accessible)."""
    try:
        resp = client.list()
        raw_models = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])
        names: list[str] = []
        for entry in raw_models:
            if isinstance(entry, dict):
                name = entry.get("model") or entry.get("name")
            else:
                name = getattr(entry, "model", None) or getattr(entry, "name", None)
            if name:
                names.append(str(name))
        return names, True
    except Exception:
        return [], False


def select_default_model(client: Any) -> tuple[str, list[str], bool]:
    """Choisit le meilleur modèle installé selon AGENT_MODEL ou PREFERRED_MODELS."""
    installed, reachable = get_installed_models(client)
    env_model = os.environ.get("AGENT_MODEL", "").strip()
    if env_model and (env_model in installed or not reachable):
        return env_model, installed, reachable

    for candidate in PREFERRED_MODELS:
        if candidate in installed:
            return candidate, installed, reachable

    if installed:
        return installed[0], installed, reachable
    return PREFERRED_MODELS[1], installed, reachable


def build_system_prompt(workspace_dir: str, swarm_enabled: bool = True) -> str:
    """Construit un prompt système concis et précis pour le tool calling natif."""
    prompt = (
        "Tu es un assistant technique local expert en développement logiciel, administration système "
        "et cybersécurité défensive/offensive autorisée (analyse, audit, scripts, CTF, labo local).\n"
        f"Dossier de travail actif : {workspace_dir}\n\n"
        "Règles de fonctionnement :\n"
        "1. Réponds directement en texte clair si aucun outil n'est nécessaire (questions théoriques, explications, conseils).\n"
        "2. Quand une action sur les fichiers, le terminal ou le web est requise, appelle directement l'outil approprié sans l'annoncer avant.\n"
        "3. Lis toujours un fichier avec `read_file` avant de le modifier avec `edit_file`, et vérifie le dossier avec `list_dir` si un chemin est incertain.\n"
        "4. Ne devine jamais le contenu d'un fichier ni la sortie d'une commande : appuie-toi uniquement sur ce que les outils retournent.\n"
        "5. En cas d'erreur d'un outil, analyse le message et change d'approche ou de paramètres ; ne répète jamais deux fois le même appel identique.\n"
        "6. Réponds en français de manière structurée, précise et concise."
    )
    if swarm_enabled:
        prompt += (
            "\n\nMode Essaim (Swarm) actif via `delegate_task(role, task)` :\n"
            "- Workers disponibles : `researcher` (exploration lecture seule), `coder` (implémentation + tests), "
            "`security` (audit et cybersécurité autorisée), `reviewer` (relecture et vérification).\n"
            "- Traite directement les questions simples ou vérifications en 1 étape ; délègue les explorations complètes, "
            "modifications de code, audits de sécurité ou revues de tests au worker adapté, puis synthétise ses résultats pour l'utilisateur."
        )
    return prompt
