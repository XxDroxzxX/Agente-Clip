"""generate_script.py – Genera el guion del video a partir de la estrategia seleccionada.
Utiliza un modelo LLM local mediante llama‑cpp‑python (por ejemplo, llama‑7B‑Instruct o Mistral‑7B).
Guarda el guion en `data/script.txt`.
"""
import json, os, sys
from pathlib import Path
import yaml
from llama_cpp import Llama

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        print("[ERROR] config.yaml not found")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_strategy():
    strat_path = DATA_DIR / "selected_strategy.json"
    if not strat_path.is_file():
        print("[ERROR] selected_strategy.json not found – run analyse first.")
        sys.exit(1)
    with open(strat_path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_prompt(strategy, language="es"):
    prompt = f"Eres un creador de contenido para YouTube. Basándote en el video más exitoso que tiene el título '{strategy['title']}' y una duración de {strategy['duration']}, genera un guion completo para un nuevo video que reproduzca la misma estrategia pero con un tema original sobre '{strategy['title']}'.\n"
    prompt += "El guion debe incluir:\n"
    prompt += "- Introducción atractiva (primeras 15 segundos).\n"
    prompt += "- Desarrollo con al menos tres bloques de contenido con ejemplos claros.\n"
    prompt += "- Llamado a la acción (suscribirse, comentar, seguir en otras redes).\n"
    prompt += "- Cierre con resumen rápido.\n"
    prompt += f"Escribe el guion en {language} y utiliza un tono amigable y dinámico."
    return prompt

def generate_script(model_path, prompt, max_tokens=1024, temperature=0.7):
    llm = Llama(model_path=model_path, n_ctx=2048, n_threads=os.cpu_count())
    output = llm(prompt, max_tokens=max_tokens, temperature=temperature)
    return output['choices'][0]['text']

def main():
    cfg = load_config()
    strategy = load_strategy()
    model_path = cfg.get("llm", {}).get("model_path")
    if not model_path:
        print("[ERROR] LLM model_path not defined in config.yaml (section llm).")
        sys.exit(1)
    language = cfg.get("options", {}).get("language", "es")
    prompt = build_prompt(strategy, language)
    print("[INFO] Generating script …")
    script = generate_script(model_path, prompt)
    out_path = DATA_DIR / "script.txt"
    out_path.write_text(script, encoding="utf-8")
    print(f"[INFO] Script saved to {out_path}")

if __name__ == "__main__":
    main()
