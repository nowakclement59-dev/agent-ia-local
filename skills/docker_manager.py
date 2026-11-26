import subprocess

SKILL_PROMPT = '- `{"action": "docker_manager", "command": "ps|restart|logs", "container_name": "..."}` (Skill Docker : lister les conteneurs, redémarrer un service ou lire les logs)'

def execute(data: dict) -> tuple[str, bool]:
    command = data.get("command", "ps").strip().lower()
    container = data.get("container_name", "").strip()
    
    try:
        if command == "ps":
            res = subprocess.run(["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"], capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return f"Erreur Docker : {res.stderr}", True
            return f"🐳 Conteneurs Actifs :\n{res.stdout.strip()}", False
            
        elif command == "restart":
            if not container:
                return "Erreur : 'container_name' est requis pour restart.", True
            res = subprocess.run(["docker", "restart", container], capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                return f"Erreur Docker : {res.stderr}", True
            return f"🐳 Conteneur '{container}' redémarré avec succès.", False
            
        elif command == "logs":
            if not container:
                return "Erreur : 'container_name' est requis pour logs.", True
            res = subprocess.run(["docker", "logs", "--tail", "50", container], capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return f"Erreur Docker : {res.stderr}", True
            return f"🐳 Logs de '{container}' (50 dernières lignes) :\n{res.stdout.strip()[-1500:]}", False
            
        return f"Commande Docker inconnue : {command}", True
    except FileNotFoundError:
        return "Erreur : Docker n'est pas installé ou pas dans le PATH.", True
    except Exception as e:
        return f"Exception Skill Docker : {str(e)}", True
