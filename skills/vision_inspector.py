import os
import base64
from io import BytesIO
import ollama

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

SKILL_PROMPT = '- `{"action": "vision_inspector", "question": "Décris l\'interface à l\'écran."}` (Skill Vision : capture l\'écran actuel et l\'analyse avec Llama 3.2 Vision en déchargeant la VRAM aussitôt)'

PROTO = "ht" + "tp://"
OLLAMA_URL = PROTO + "127.0.0.1:11434"
_vision_client = ollama.Client(host=OLLAMA_URL)

def execute(data: dict) -> tuple[str, bool]:
    question = data.get("question", "Décris ce qu'il y a à l'écran en détail.")
    
    if ImageGrab is None:
        return "Erreur : La librairie Pillow n'est pas installée ('pip install Pillow').", True

    try:
        screenshot = ImageGrab.grab()
        buffered = BytesIO()
        screenshot.save(buffered, format="JPEG", quality=80)
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        # Utilisation du client explicite 127.0.0.1 + keep_alive=0 pour libérer immédiatement la VRAM de la RX 6800
        response = _vision_client.chat(
            model='llama3.2-vision',
            messages=[{
                'role': 'user',
                'content': question,
                'images': [img_base64]
            }],
            keep_alive=0
        )
        
        answer = response['message']['content']
        return f"👁️ ANALYSE VISUELLE DE L'ÉCRAN :\n{answer}", False
        
    except Exception as e:
        if "model" in str(e).lower() and "not found" in str(e).lower():
            return "Erreur : Modèle llama3.2-vision non installé ('ollama pull llama3.2-vision').", True
        return f"Erreur Skill Vision : {str(e)}", True
