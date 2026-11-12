"""fetch_videos.py – Obtiene los videos más vistos de un nicho usando la YouTube Data API.
Guarda un CSV en data/top_videos.csv con columnas: video_id,title,views,likes,comments,duration.
"""
import os, sys, csv
from pathlib import Path
import yaml
from googleapiclient.discovery import build
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        print("[ERROR] config.yaml not found")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def fetch_top_videos(api_key, query, max_results=20):
    yt = build("youtube", "v3", developerKey=api_key)
    search_resp = yt.search().list(
        q=query,
        part="id,snippet",
        type="video",
        order="viewCount",
        maxResults=max_results,
    ).execute()
    video_ids = [item["id"]["videoId"] for item in search_resp["items"]]
    videos = yt.videos().list(
        part="statistics,contentDetails,snippet",
        id=",".join(video_ids)
    ).execute()
    rows = []
    for v in videos["items"]:
        rows.append({
            "video_id": v["id"],
            "title": v["snippet"]["title"],
            "views": int(v["statistics"].get("viewCount", 0)),
            "likes": int(v["statistics"].get("likeCount", 0)),
            "comments": int(v["statistics"].get("commentCount", 0)),
            "duration": v["contentDetails"]["duration"],
        })
    return pd.DataFrame(rows)

def main():
    cfg = load_config()
    api_key = cfg.get("youtube", {}).get("api_key")
    if not api_key:
        print("[ERROR] YouTube API key missing in config.yaml")
        sys.exit(1)
    niche = cfg.get("options", {}).get("niche_query", "")
    if not niche:
        print("[ERROR] niche_query not defined in config.yaml")
        sys.exit(1)
    df = fetch_top_videos(api_key, niche, max_results=30)
    out_path = DATA_DIR / "top_videos.csv"
    df.to_csv(out_path, index=False)
    print(f"[INFO] Saved {len(df)} videos to {out_path}")

if __name__ == "__main__":
    main()
