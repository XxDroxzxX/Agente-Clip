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
    try:
        creds = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="consent",
                                      authorization_prompt_message="", timeout_seconds=300, success_message=
                                      "Canal conectado. Ya puedes cerrar esta pestaña y volver al Agente de Clips.")
    except Exception as e:
        text = str(e).lower()
        if "access_denied" in text:
            raise RuntimeError("Google denegó el acceso. Si viste «Acceso bloqueado», agrega tu cuenta de Google como "
                               "usuario de prueba o publica la app (ver «¿Cómo lo obtengo?» en Conexiones).")
        raise RuntimeError("No se completó la autorización en 5 minutos. Si Google mostró «Acceso bloqueado: la app no "
                           "completó la verificación», sigue los pasos de «¿Cómo lo obtengo?» en Conexiones.")
    if creds is None:
        raise RuntimeError("No se recibió la autorización de Google. Vuelve a intentarlo.")
    S.set_secret("youtube_token", creds.to_json())
    return channel_name(creds) or "canal conectado"


EXPIRED_MSG = ("La autorización de YouTube venció o fue revocada. Vuelve a conectar el canal en Configuración → "
               "Conexiones. Si vence cada 7 días, es porque la app de Google está en modo «Prueba»: publícala "
               "(ver «¿Cómo lo obtengo?»).")


class YouTubeAuthExpired(RuntimeError):
    pass


def get_credentials() -> Credentials | None:
    from google.auth.exceptions import RefreshError

    info = S.get_json_secret("youtube_token")
    if not info:
        return None
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:  # invalid_grant: vencida (modo Prueba = 7 días) o revocada
            raise YouTubeAuthExpired(EXPIRED_MSG)
        S.set_secret("youtube_token", creds.to_json())
    return creds if creds.valid else None


def status() -> tuple[str | None, str | None]:
    """(nombre del canal, error). Para mostrar el estado real de la conexión."""
    try:
        creds = get_credentials()
    except YouTubeAuthExpired as e:
        return None, str(e)
    except Exception as e:
        return None, f"No se pudo verificar la conexión: {str(e)[:150]}"
    if not creds:
        return None, EXPIRED_MSG
    return channel_name(creds), None


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
           language: str, is_short: bool, on_progress: Callable[[float], None],
           thumbnail: Path | None = None) -> dict:
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
    notes = []
    if actual != privacy:
        notes.append(f"YouTube dejó el video como «{actual}». Los proyectos de API sin auditoría "
                     "solo pueden publicar en privado.")
    if thumbnail and Path(thumbnail).is_file() and not is_short:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
        except Exception as e:
            text = str(e)
            if "forbidden" in text.lower() or "403" in text:
                notes.append("La miniatura no se aplicó: YouTube exige verificar el canal con tu teléfono "
                             "(youtube.com/verify) para usar miniaturas personalizadas.")
            else:
                notes.append(f"La miniatura no se aplicó ({text[:150]}).")
    return {"platform_id": vid, "url": url, "privacy": actual, "note": " ".join(notes)}


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
