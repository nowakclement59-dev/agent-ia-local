import requests
import os

SKILL_PROMPT = '- `{"action": "tavily_search", "query": "PyQt6 QScrollArea dark stylesheet example"}` (Skill Tavily : recherche web technique pour documentation API ou résolution de bugs)'

def execute(data: dict) -> tuple[str, bool]:
    query = data.get("query", "").strip()
    if not query:
        return "Erreur : La requête (query) est vide.", True
    API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
    if not API_KEY or API_KEY == "METTRE_TA_CLE_ICI":
        return "Erreur : Configure la variable d'environnement TAVILY_API_KEY dans .env.", True

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": API_KEY, "query": query, "search_depth": "advanced", "include_answer": True, "max_results": 5},
            timeout=25
        )
        if response.status_code != 200:
            return f"Erreur Tavily API : {response.text}", True
        result = response.json()
        answer = result.get("answer", "Pas de réponse synthétique trouvée.")
        sources = "\n".join([f"- {r.get('title', 'Source')}: {r.get('content', '')[:180]}..." for r in result.get("results", [])])
        return f"🔎 RÉPONSE TAVILY AI :\n{answer}\n\nSOURCES :\n{sources}", False
    except Exception as e:
        return f"Exception Skill Tavily : {str(e)}", True
