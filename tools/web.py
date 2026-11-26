"""Outil de recherche web via l'API Tavily (clé lue uniquement depuis TAVILY_API_KEY)."""

import os

import httpx

from tools.registry import ToolRegistry


def register_web_tool(registry: ToolRegistry) -> None:
    """Enregistre l'outil `web_search`."""

    def web_search(query: str) -> str:
        q = (query or "").strip()
        if not q:
            return "Erreur : le paramètre 'query' est vide."
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            return "Erreur : TAVILY_API_KEY non configurée dans .env."

        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": q,
                "search_depth": "advanced",
                "include_answer": True,
                "max_results": 5,
            },
            timeout=25.0,
        )
        if resp.status_code != 200:
            return f"Erreur Tavily ({resp.status_code}) : {resp.text[:400]}"

        data = resp.json()
        parts: list[str] = []
        if data.get("answer"):
            parts.append(f"Synthèse : {data['answer']}")
        for item in data.get("results", []):
            title = item.get("title", "Source")
            url = item.get("url", "")
            snippet = (item.get("content") or "")[:250].replace("\n", " ")
            parts.append(f"- {title} ({url})\n  {snippet}")
        return "\n".join(parts) if parts else "Aucun résultat trouvé."

    registry.register(
        name="web_search",
        description="Effectue une recherche web technique (documentation, CVE, erreurs) via Tavily.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Requête de recherche web."},
            },
            "required": ["query"],
        },
        handler=web_search,
    )
