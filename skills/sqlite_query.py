import sqlite3
import os

SKILL_PROMPT = '- `{"action": "sqlite_query", "db_path": "repo_index.db", "query": "SELECT * FROM file_index_v37"}` (Skill SQL : exécute une requête SELECT/PRAGMA sur une base SQLite locale)'

def execute(data: dict) -> tuple[str, bool]:
    db_path = data.get("db_path", "").strip()
    query = data.get("query", "").strip()
    
    if not db_path or not query:
        return "Erreur : 'db_path' et 'query' sont requis.", True
        
    abs_p = os.path.abspath(db_path)
    if not os.path.isfile(abs_p):
        return f"Erreur : La base de données '{abs_p}' est introuvable.", True
        
    if not query.lower().startswith(("select", "pragma")):
        return "Erreur de sécurité : Ce skill n'autorise que les requêtes de lecture (SELECT / PRAGMA).", True

    try:
        conn = sqlite3.connect(abs_p)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return "🗄️ Requête exécutée avec succès, mais aucun résultat retourné.", False
            
        columns = [description[0] for description in cursor.description]
        header = "| " + " | ".join(columns) + " |"
        separator = "|-" + "-|-".join(["-" * len(c) for c in columns]) + "-|"
        table_lines = [header, separator]
        
        for row in rows[:20]:
            str_row = [str(val) if val is not None else "NULL" for val in row]
            table_lines.append("| " + " | ".join(str_row) + " |")
            
        result_str = "\n".join(table_lines)
        if len(rows) > 20:
            result_str += f"\n... (et {len(rows) - 20} autres lignes tronquées)"
            
        conn.close()
        return f"🗄️ Résultats SQL :\n{result_str}", False
    except Exception as e:
        return f"Exception Skill SQLite : {str(e)}", True
