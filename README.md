# Agent IA Local — Orchestrateur Swarm & Tool Calling (Ollama)

Assistant technique local en Python propulsé par **Ollama**, doté d'une architecture **Swarm (multi-agents) Zero-Swap VRAM**, de **Tool Calling natif**, de skills modulaires et d'une intégration **MCP (Model Context Protocol)**.

---

## Architecture & Fonctionnalités

- **Orchestrateur Swarm Zero-Swap VRAM (`agent/swarm.py`)** : délégation vers des sous-agents spécialisés (`researcher`, `coder`, `security`, `reviewer`) partageant le modèle actif en VRAM sans rechargement.
- **Boucle agentique & Tool Calling natif (`agent/loop.py`, `agent/context.py`)** : gestion du contexte et élagage automatique selon le budget de tokens, streaming, mode réflexion (`/think`), annulation (`/undo`) et sélection automatique du modèle (`agent/config.py`).
- **Outils natifs (`tools/`)** :
  - `filesystem.py` : lecture, édition, écriture, listage et recherche (`grep_search`).
  - `shell.py` : exécution sécurisée de commandes locales.
  - `web.py` : recherche web via API Tavily (`TAVILY_API_KEY`).
  - `registry.py` : registre d'outils typés et troncature intelligente des sorties.
- **Skills modulaires (`skills/`)** :
  - `docker_manager.py`, `sysadmin_metrics.py`, `sqlite_query.py`, `python_repl.py`, `pylint_check.py`, `tavily_search.py`, `vision_inspector.py`, `lol_stats.py`.
- **Intégration MCP (`mcp_config.json`, `mcp_riot.py`, `mcp_opgg.py`)** : connexion à des serveurs MCP locaux et externes (mémoire persistante, outils Riot / OP.GG).
- **Tests unitaires (`tests/test_agent_core.py`)** : suite `pytest` avec mock `FakeOllamaClient` couvrant le registre, le contexte, la boucle et l'orchestrateur Swarm.

---

## Installation & Lancement

### Prérequis
- Python 3.10+
- [Ollama](https://ollama.com/) installé et démarré (`ollama serve`)

### Configuration
1. Copie `.env.example` vers `.env` et adapte les variables si besoin :
   ```bash
   cp .env.example .env
   ```
   Variables disponibles :
   - `AGENT_MODEL` : modèle Ollama par défaut (ex. `qwen3:14b`, `qwen2.5-coder:14b`, etc.)
   - `AGENT_NUM_CTX` : taille de la fenêtre de contexte (défaut : `16384`)
   - `TAVILY_API_KEY` : clé API Tavily (optionnelle, pour la recherche web)
2. Installe les dépendances (`ollama`, `rich`, `prompt_toolkit`, `requests`, `pytest`) et lance l'agent :
   ```bash
   python main.py
   ```

### Tests
```bash
pytest
```
