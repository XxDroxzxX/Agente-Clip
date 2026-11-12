"""analyse.py – Analiza los videos obtenidos y elige la estrategia ganadora.

Si existe data/learned_weights.json (generado por metrics_loop.py),
usa esos pesos aprendidos. Si no, usa pesos por defecto.

Guarda data/selected_strategy.json con los campos del video ganador.
"""
import json, sys
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_WEIGHTS = {"views": 0.5, "likes": 0.3, "comments": 0.2}


def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        print("[ERROR] config.yaml not found")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_weights():
    """Carga pesos aprendidos si existen, si no usa los por defecto."""
    learned_path = DATA_DIR / "learned_weights.json"
    if learned_path.is_file():
        with open(learned_path, "r", encoding="utf-8") as f:
            w = json.load(f)
        print(f"[INFO] Usando pesos aprendidos: {w}")
        return w
    print(f"[INFO] Usando pesos por defecto: {DEFAULT_WEIGHTS}")
    return DEFAULT_WEIGHTS


def compute_score(row, weights):
    return (
        row["views"] * weights.get("views", 0.5)
        + row["likes"] * weights.get("likes", 0.3)
        + row["comments"] * weights.get("comments", 0.2)
    )


def main():
    csv_path = DATA_DIR / "top_videos.csv"
    if not csv_path.is_file():
        print("[ERROR] top_videos.csv not found – run fetch_videos first.")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    weights = load_weights()
    df["score"] = df.apply(lambda r: compute_score(r, weights), axis=1)

    # Ordenar por score descendente
    df_sorted = df.sort_values("score", ascending=False)

    # Top 3 para contexto del LLM
    top3 = df_sorted.head(3).to_dict("records")
    best = df_sorted.iloc[0]

    result = {
        "video_id": best["video_id"],
        "title": best["title"],
        "score": float(best["score"]),
        "views": int(best["views"]),
        "likes": int(best["likes"]),
        "comments": int(best["comments"]),
        "duration": best["duration"],
        "top_3": top3,  # Los 3 mejores para dar mas contexto al LLM
    }
    out_path = DATA_DIR / "selected_strategy.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[INFO] Estrategia ganadora: '{best['title']}' (score: {best['score']:.0f})")
    print(f"[INFO] Top 3 guardados en {out_path}")


if __name__ == "__main__":
    main()
