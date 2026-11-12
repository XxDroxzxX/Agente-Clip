"""YouTube: OAuth, subida de videos/Shorts y métricas."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from .. import settings as S

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def connect_interactive() -> str:
    """Abre el navegador para autorizar el canal. Bloquea hasta completar."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    raw = S.get_secret("youtube_client_secret")
    if not raw:
        raise RuntimeError("Primero guarda el OAuth client (JSON) de YouTube.")
    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("El OAuth client de YouTube no es un JSON válido.")
    flow = InstalledAppFlow.from_client_config(config, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="consent",
                                  authorization_prompt_message="", success_message=
                                  "Canal conectado. Ya puedes cerrar esta pestaña y volver al Agente de Clips.")
    S.set_secret("youtube_token", creds.to_json())
    return channel_name(creds) or "canal conectado"


def get_credentials() -> Credentials | None:
    info = S.get_json_secret("youtube_token")
    if not info:
        return None
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        S.set_secret("youtube_token", creds.to_json())
    return creds if creds.valid else None


def _client(creds=None):
    from googleapiclient.discovery import build
    creds = creds or get_credentials()
    if not creds:
        raise RuntimeError("YouTube no está conectado (Configuración → Conexiones).")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_name(creds=None) -> str | None:
    try:
        resp = _client(creds).channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        return items[0]["snippet"]["title"] if items else None
    except Exception:
        return None


def upload(video: Path, title: str, description: str, tags: list[str], privacy: str, category: str,
           language: str, is_short: bool, on_progress: Callable[[float], None]) -> dict:
    from googleapiclient.http import MediaFileUpload

    yt = _client()
    if is_short and "#shorts" not in title.lower():
        title = f"{title[:90]} #Shorts"
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [t.lstrip("#") for t in tags][:15],
            "categoryId": category,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            on_progress(status.progress())
    vid = resp["id"]
    actual = resp.get("status", {}).get("privacyStatus", privacy)
    url = f"https://youtube.com/shorts/{vid}" if is_short else f"https://youtu.be/{vid}"
    note = ""
    if actual != privacy:
        note = (f"YouTube dejó el video como «{actual}». Los proyectos de API sin auditoría "
                "solo pueden publicar en privado.")
    return {"platform_id": vid, "url": url, "privacy": actual, "note": note}


def fetch_stats(ids: list[str]) -> dict[str, dict]:
    """Estadísticas por id. Usa OAuth (ve videos privados) o la API key como respaldo."""
    from googleapiclient.discovery import build
    creds = None
    try:
        creds = get_credentials()
    except Exception:
        pass
    if creds:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    else:
        key = S.get_secret("youtube_api_key")
        if not key:
            return {}
        yt = build("youtube", "v3", developerKey=key, cache_discovery=False)
    out = {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
        for v in resp.get("items", []):
            st = v.get("statistics", {})
            out[v["id"]] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                            "comments": int(st.get("commentCount", 0))}
    return out
