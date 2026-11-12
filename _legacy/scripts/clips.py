"""clips.py – Extrae clips cortos (15-60s) del video final y los sube como Shorts/Reels.

Estrategia simplificada:
  - Divide el video en segmentos de ~30s.
  - Reformatea a vertical (9:16) para Shorts/Reels/TikTok.
  - Sube cada clip a YouTube Shorts, Facebook Reels y TikTok.
"""
import json, os, subprocess, sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CLIPS_DIR = PROJECT_ROOT / "output" / "clips"


def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_video_duration(video_path):
    """Obtiene la duracion del video en segundos usando ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        print(f"[WARN] No se pudo obtener duracion: {result.stderr}")
        return 0


def extract_clip(input_path, output_path, start_sec, duration_sec=30):
    """Extrae un clip y lo convierte a formato vertical 9:16 (1080x1920)."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", str(input_path),
        "-t", str(duration_sec),
        # Escalar a vertical 9:16 con padding negro
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def upload_clip_youtube(cfg, clip_path, clip_num):
    """Sube un clip como YouTube Short (video corto vertical)."""
    try:
        # Reutilizar la logica de upload.py
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from upload import get_youtube_credentials, load_script_text
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        title, desc, tags = load_script_text()
        creds = get_youtube_credentials(cfg)
        yt = build("youtube", "v3", credentials=creds)
        body = {
            "snippet": {
                "title": f"{title[:80]} - Clip #{clip_num} #Shorts",
                "description": f"Clip #{clip_num}\n{desc[:200]}\n\n{' '.join(tags)} #Shorts",
                "tags": [t.replace('#', '') for t in tags] + ["Shorts"],
                "categoryId": "22",
            },
            "status": {"privacyStatus": "public"},
        }
        media = MediaFileUpload(str(clip_path), mimetype="video/mp4")
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = req.execute()
        print(f"[YOUTUBE SHORT] Clip #{clip_num} subido: https://youtu.be/{resp['id']}")
        return resp["id"]
    except Exception as e:
        print(f"[YOUTUBE SHORT] Error clip #{clip_num}: {e}")
        return None


def upload_clip_tiktok(cfg, clip_path, clip_num):
    """Sube un clip a TikTok."""
    try:
        from upload import upload_tiktok, load_script_text
        title, desc, tags = load_script_text()
        result = upload_tiktok(cfg, clip_path, f"Clip #{clip_num} - {title[:50]}", desc[:150], tags)
        return result
    except Exception as e:
        print(f"[TIKTOK CLIP] Error clip #{clip_num}: {e}")
        return None


def upload_clip_facebook(cfg, clip_path, clip_num):
    """Sube un clip como Reel a Facebook."""
    try:
        from upload import upload_facebook, load_script_text
        title, desc, tags = load_script_text()
        result = upload_facebook(cfg, clip_path, f"Clip #{clip_num} - {title[:50]}", desc[:150], tags)
        return result
    except Exception as e:
        print(f"[FACEBOOK REEL] Error clip #{clip_num}: {e}")
        return None


def main():
    cfg = load_config()
    video_path = DATA_DIR / "final_video.mp4"
    if not video_path.is_file():
        print("[ERROR] final_video.mp4 no encontrado. Ejecuta make_video primero.")
        sys.exit(1)

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    duration = get_video_duration(video_path)
    if duration <= 0:
        print("[ERROR] No se pudo determinar la duracion del video.")
        sys.exit(1)

    clip_duration = 30  # segundos por clip
    num_clips = max(1, int(duration // clip_duration))
    # Limitar a maximo 5 clips
    num_clips = min(num_clips, 5)

    print(f"[INFO] Video de {duration:.0f}s -> generando {num_clips} clip(s) de {clip_duration}s")

    clip_results = []
    for i in range(num_clips):
        start = i * clip_duration
        clip_path = CLIPS_DIR / f"clip_{i+1}.mp4"
        print(f"\n[INFO] Extrayendo clip #{i+1} (inicio: {start}s, duracion: {clip_duration}s)...")
        try:
            extract_clip(video_path, clip_path, start, clip_duration)
            print(f"[INFO] Clip guardado: {clip_path}")

            # Subir a las tres plataformas
            yt_id = upload_clip_youtube(cfg, clip_path, i + 1)
            tt_id = upload_clip_tiktok(cfg, clip_path, i + 1)
            fb_id = upload_clip_facebook(cfg, clip_path, i + 1)

            clip_results.append({
                "clip": i + 1,
                "file": str(clip_path),
                "youtube_short": yt_id,
                "tiktok": tt_id,
                "facebook_reel": fb_id,
            })
        except Exception as e:
            print(f"[ERROR] Fallo al procesar clip #{i+1}: {e}")

    # Guardar resultados
    out_path = DATA_DIR / "clip_uploads.json"
    out_path.write_text(json.dumps(clip_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[INFO] Resultados de clips guardados en {out_path}")


if __name__ == "__main__":
    main()
