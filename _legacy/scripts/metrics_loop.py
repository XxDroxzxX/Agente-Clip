"""metrics_loop.py – Recopila metricas post-publicacion y aprende para mejorar.

1. Lee los IDs de subida (upload_ids.json + clip_uploads.json).
2. Consulta metricas de YouTube Analytics, TikTok y Facebook.
3. Guarda todo en data/metrics_history.csv (acumulativo).
4. Calcula insights y ajusta los pesos del scoring para la proxima iteracion.
"""
import csv, json, os, sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ────────────────────────────────────────────────
# YouTube Analytics
# ────────────────────────────────────────────────
def fetch_youtube_metrics(cfg, video_ids):
    """Obtiene metricas basicas de YouTube para una lista de video IDs."""
    api_key = cfg.get("youtube", {}).get("api_key", "")
    if not api_key or not video_ids:
        return []

    from googleapiclient.discovery import build
    yt = build("youtube", "v3", developerKey=api_key)
    ids_str = ",".join([vid for vid in video_ids if vid])
    if not ids_str:
        return []

    resp = yt.videos().list(
        part="statistics,snippet",
        id=ids_str,
    ).execute()

    rows = []
    for v in resp.get("items", []):
        stats = v.get("statistics", {})
        rows.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "platform": "youtube",
            "video_id": v["id"],
            "title": v["snippet"]["title"][:100],
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "favorites": int(stats.get("favoriteCount", 0)),
        })
    return rows


# ────────────────────────────────────────────────
# Facebook Insights
# ────────────────────────────────────────────────
def fetch_facebook_metrics(cfg, video_ids):
    """Obtiene metricas de Facebook para videos publicados."""
    token = cfg.get("facebook", {}).get("page_access_token", "")
    if not token or not video_ids:
        return []

    rows = []
    for vid in video_ids:
        if not vid:
            continue
        url = f"https://graph.facebook.com/v18.0/{vid}"
        resp = requests.get(url, params={
            "fields": "title,description,length,views,likes.summary(true),comments.summary(true)",
            "access_token": token,
        })
        if resp.status_code == 200:
            data = resp.json()
            rows.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "platform": "facebook",
                "video_id": vid,
                "title": data.get("title", "")[:100],
                "views": data.get("views", 0),
                "likes": data.get("likes", {}).get("summary", {}).get("total_count", 0),
                "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                "favorites": 0,
            })
        else:
            print(f"[FACEBOOK METRICS] Error para {vid}: {resp.status_code}")
    return rows


# ────────────────────────────────────────────────
# Guardar metricas en historico
# ────────────────────────────────────────────────
def save_metrics(all_rows):
    """Agrega las metricas al archivo CSV historico."""
    csv_path = DATA_DIR / "metrics_history.csv"
    file_exists = csv_path.is_file()
    fieldnames = ["date", "platform", "video_id", "title", "views", "likes", "comments", "favorites"]

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"[INFO] {len(all_rows)} registros agregados a {csv_path}")


# ────────────────────────────────────────────────
# Aprendizaje: ajustar pesos del scoring
# ────────────────────────────────────────────────
def learn_and_update_weights():
    """Analiza el historico de metricas y ajusta los pesos para analyse.py."""
    csv_path = DATA_DIR / "metrics_history.csv"
    if not csv_path.is_file():
        print("[INFO] No hay historico suficiente para aprender. Se usaran pesos por defecto.")
        return

    df = pd.read_csv(csv_path)
    if len(df) < 3:
        print("[INFO] Menos de 3 registros. Se necesitan mas datos para ajustar pesos.")
        return

    # Calcular correlacion de cada metrica con 'views' (nuestro KPI principal)
    numeric = df[["views", "likes", "comments"]].astype(float)
    corr = numeric.corr()["views"].drop("views")

    # Normalizar a pesos que sumen 1.0
    total = corr.abs().sum()
    if total == 0:
        return

    weights = {
        "views": 0.5,  # siempre un peso base alto para views
        "likes": round(float(corr.get("likes", 0.3).item() if hasattr(corr.get("likes", 0.3), 'item') else corr.get("likes", 0.3)) * 0.5 / total, 3),
        "comments": round(float(corr.get("comments", 0.2).item() if hasattr(corr.get("comments", 0.2), 'item') else corr.get("comments", 0.2)) * 0.5 / total, 3),
    }

    # Guardar pesos aprendidos
    weights_path = DATA_DIR / "learned_weights.json"
    weights_path.write_text(json.dumps(weights, indent=2), encoding="utf-8")
    print(f"[INFO] Pesos aprendidos guardados en {weights_path}")
    print(f"       views={weights['views']}, likes={weights['likes']}, comments={weights['comments']}")

    # Generar insight resumido
    insights_path = DATA_DIR / "insights.txt"
    best_platform = df.groupby("platform")["views"].mean().idxmax() if len(df.groupby("platform")) > 0 else "N/A"
    avg_views = df["views"].mean()
    avg_likes = df["likes"].mean()

    insight = f"""=== INSIGHTS ({datetime.now().strftime('%Y-%m-%d')}) ===
Total registros analizados: {len(df)}
Plataforma con mejor rendimiento promedio: {best_platform}
Promedio de vistas: {avg_views:.0f}
Promedio de likes: {avg_likes:.0f}
Correlacion likes->views: {corr.get('likes', 0):.3f}
Correlacion comments->views: {corr.get('comments', 0):.3f}
Pesos actualizados: {json.dumps(weights)}
"""
    insights_path.write_text(insight, encoding="utf-8")
    print(f"[INFO] Insights guardados en {insights_path}")


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
def main():
    cfg = load_config()
    all_metrics = []

    # Leer IDs de videos subidos
    upload_path = DATA_DIR / "upload_ids.json"
    clip_path = DATA_DIR / "clip_uploads.json"

    yt_ids = []
    fb_ids = []

    if upload_path.is_file():
        uploads = json.loads(upload_path.read_text(encoding="utf-8"))
        if uploads.get("youtube"):
            yt_ids.append(uploads["youtube"])
        if uploads.get("facebook"):
            fb_ids.append(uploads["facebook"])

    if clip_path.is_file():
        clips = json.loads(clip_path.read_text(encoding="utf-8"))
        for c in clips:
            if c.get("youtube_short"):
                yt_ids.append(c["youtube_short"])
            if c.get("facebook_reel"):
                fb_ids.append(c["facebook_reel"])

    # Recopilar metricas
    print("[INFO] Recopilando metricas de YouTube...")
    yt_metrics = fetch_youtube_metrics(cfg, yt_ids)
    all_metrics.extend(yt_metrics)
    print(f"       {len(yt_metrics)} videos analizados")

    print("[INFO] Recopilando metricas de Facebook...")
    fb_metrics = fetch_facebook_metrics(cfg, fb_ids)
    all_metrics.extend(fb_metrics)
    print(f"       {len(fb_metrics)} videos analizados")

    # TikTok Analytics requiere Business API (no disponible en sandbox basico)
    print("[INFO] TikTok Analytics: requiere Business API (omitido en modo sandbox).")

    if all_metrics:
        save_metrics(all_metrics)
    else:
        print("[INFO] No se recopilaron metricas (videos muy recientes o IDs no validos).")

    # Aprendizaje
    print("\n[INFO] Ejecutando modulo de aprendizaje...")
    learn_and_update_weights()

    print("\n[INFO] Ciclo de metricas y aprendizaje completado.")


if __name__ == "__main__":
    main()
