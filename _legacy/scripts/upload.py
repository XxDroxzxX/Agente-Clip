"""upload.py – Sube el video final a YouTube, TikTok y Facebook.

YouTube:  usa OAuth 2.0 con client_secret.json (flujo interactivo la 1ra vez).
TikTok:   usa access_token para subir via Content Posting API.
Facebook: usa page_access_token via Graph API.
"""
import json, os, sys, pickle
from pathlib import Path

import requests
import yaml
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SCOPES_YT = ["https://www.googleapis.com/auth/youtube.upload"]


def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_script_text():
    """Lee el guion para extraer titulo, descripcion y hashtags."""
    script_path = DATA_DIR / "script.txt"
    if not script_path.is_file():
        return "Video generado por IA", "Video creado automaticamente.", []
    text = script_path.read_text(encoding="utf-8")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0][:100] if lines else "Video IA"
    description = "\n".join(lines[:10]) if len(lines) > 1 else title
    hashtags = ["#IA", "#viral", "#trending", "#contenido", "#automatizado"]
    return title, description, hashtags


# ────────────────────────────────────────────────
# YOUTUBE UPLOAD
# ────────────────────────────────────────────────
def get_youtube_credentials(cfg):
    """Obtiene credenciales OAuth para YouTube. La primera vez abre el navegador."""
    token_path = PROJECT_ROOT / "youtube_token.pickle"
    creds = None
    if token_path.is_file():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        cs_file = PROJECT_ROOT / cfg["youtube"].get("client_secrets_file", "client_secret.json")
        flow = InstalledAppFlow.from_client_secrets_file(str(cs_file), SCOPES_YT)
        creds = flow.run_local_server(port=8586, open_browser=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
    return creds


def upload_youtube(cfg, video_path, title, description, tags):
    print("[YOUTUBE] Autenticando...")
    creds = get_youtube_credentials(cfg)
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title,
            "description": description + "\n\n" + " ".join(tags),
            "tags": [t.replace("#", "") for t in tags],
            "categoryId": "22",
            "defaultLanguage": "es",
        },
        "status": {"privacyStatus": "public"},
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    print("[YOUTUBE] Subiendo video...")
    response = req.execute()
    vid = response["id"]
    print(f"[YOUTUBE] OK – https://youtu.be/{vid}")
    return vid


# ────────────────────────────────────────────────
# TIKTOK UPLOAD
# ────────────────────────────────────────────────
def upload_tiktok(cfg, video_path, title, description, tags):
    token = cfg.get("tiktok", {}).get("access_token", "")
    if not token:
        print("[TIKTOK] SKIP – access_token no configurado. Ejecuta: python scripts/tiktok_auth.py")
        return None

    headers_auth = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    file_size = os.path.getsize(video_path)

    # 1. Inicializar upload
    init_url = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
    init_body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        }
    }
    print("[TIKTOK] Inicializando subida...")
    resp = requests.post(init_url, json=init_body, headers=headers_auth)
    if resp.status_code != 200:
        print(f"[TIKTOK] Error init: {resp.status_code} – {resp.text}")
        return None

    data = resp.json().get("data", {})
    upload_url = data.get("upload_url")
    publish_id = data.get("publish_id")

    if not upload_url:
        print(f"[TIKTOK] No se obtuvo upload_url: {resp.text}")
        return None

    # 2. Subir el archivo
    print("[TIKTOK] Subiendo video...")
    with open(video_path, "rb") as f:
        put_resp = requests.put(
            upload_url,
            data=f,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            },
        )
    if put_resp.status_code in (200, 201):
        print(f"[TIKTOK] OK – publish_id: {publish_id}")
    else:
        print(f"[TIKTOK] Error upload: {put_resp.status_code} – {put_resp.text}")
    return publish_id


# ────────────────────────────────────────────────
# FACEBOOK UPLOAD
# ────────────────────────────────────────────────
def upload_facebook(cfg, video_path, title, description, tags):
    token = cfg.get("facebook", {}).get("page_access_token", "")
    if not token:
        print("[FACEBOOK] SKIP – page_access_token no configurado.")
        return None

    # Obtener Page ID del token
    me_resp = requests.get(
        "https://graph.facebook.com/v18.0/me/accounts",
        params={"access_token": token},
    )
    pages = me_resp.json().get("data", [])
    if not pages:
        # Intentar subir directamente al feed del usuario
        page_id = "me"
        page_token = token
    else:
        page_id = pages[0]["id"]
        page_token = pages[0].get("access_token", token)

    url = f"https://graph-video.facebook.com/v18.0/{page_id}/videos"
    full_desc = f"{title}\n\n{description}\n\n{' '.join(tags)}"

    print("[FACEBOOK] Subiendo video...")
    with open(video_path, "rb") as f:
        resp = requests.post(
            url,
            files={"source": (video_path.name, f, "video/mp4")},
            data={
                "title": title[:100],
                "description": full_desc,
                "access_token": page_token,
            },
        )
    if resp.status_code == 200:
        vid = resp.json().get("id", "unknown")
        print(f"[FACEBOOK] OK – video_id: {vid}")
        return vid
    else:
        print(f"[FACEBOOK] Error: {resp.status_code} – {resp.text}")
        return None


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
def main():
    cfg = load_config()
    video_path = DATA_DIR / "final_video.mp4"
    if not video_path.is_file():
        print("[ERROR] final_video.mp4 no encontrado. Ejecuta make_video primero.")
        sys.exit(1)

    title, description, tags = load_script_text()

    uploads = {}

    # YouTube
    try:
        yt_id = upload_youtube(cfg, video_path, title, description, tags)
        uploads["youtube"] = yt_id
    except Exception as e:
        print(f"[YOUTUBE] Error: {e}")
        uploads["youtube"] = None

    # TikTok
    try:
        tt_id = upload_tiktok(cfg, video_path, title, description, tags)
        uploads["tiktok"] = tt_id
    except Exception as e:
        print(f"[TIKTOK] Error: {e}")
        uploads["tiktok"] = None

    # Facebook
    try:
        fb_id = upload_facebook(cfg, video_path, title, description, tags)
        uploads["facebook"] = fb_id
    except Exception as e:
        print(f"[FACEBOOK] Error: {e}")
        uploads["facebook"] = None

    out_path = DATA_DIR / "upload_ids.json"
    out_path.write_text(json.dumps(uploads, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[INFO] IDs de subida guardados en {out_path}")

    # Verificar que al menos uno tuvo exito
    ok = [k for k, v in uploads.items() if v]
    if not ok:
        print("[WARN] Ninguna plataforma tuvo exito. Revisa los errores arriba.")
    else:
        print(f"[INFO] Publicado en: {', '.join(ok)}")


if __name__ == "__main__":
    main()
