"""TikTok: OAuth (vía la interfaz), renovación de token y Content Posting API."""
from __future__ import annotations

import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Callable

import requests

from .. import settings as S

API = "https://open.tiktokapis.com"
SCOPES = "user.info.basic,video.upload,video.publish"
MIN_CHUNK = 5 * 1024 * 1024
CHUNK = 10 * 1024 * 1024
MAX_SINGLE = 64 * 1024 * 1024

_pending_states: dict[str, float] = {}


def auth_url(redirect_uri: str) -> str:
    key = S.get_secret("tiktok_client_key")
    if not key or not S.get_secret("tiktok_client_secret"):
        raise RuntimeError("Guarda primero el client key y el client secret de TikTok.")
    state = secrets.token_urlsafe(16)
    _pending_states[state] = time.time()
    q = urllib.parse.urlencode({"client_key": key, "response_type": "code", "scope": SCOPES,
                                "redirect_uri": redirect_uri, "state": state})
    return f"https://www.tiktok.com/v2/auth/authorize/?{q}"


def _store_token(data: dict):
    if "access_token" not in data:
        raise RuntimeError(f"TikTok no devolvió access_token: {data}")
    S.set_json_secret("tiktok_token", {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": time.time() + int(data.get("expires_in", 86400)),
        "refresh_expires_at": time.time() + int(data.get("refresh_expires_in", 0) or 0),
        "open_id": data.get("open_id"),
    })


def handle_callback(code: str, state: str, redirect_uri: str) -> None:
    ts = _pending_states.pop(state, None)
    if ts is None or time.time() - ts > 900:
        raise RuntimeError("Estado OAuth inválido o caducado. Vuelve a pulsar «Conectar TikTok».")
    r = requests.post(f"{API}/v2/oauth/token/", data={
        "client_key": S.get_secret("tiktok_client_key"),
        "client_secret": S.get_secret("tiktok_client_secret"),
        "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    _store_token(r.json())


def access_token() -> str:
    tok = S.get_json_secret("tiktok_token")
    if not tok:
        raise RuntimeError("TikTok no está conectado (Configuración → Conexiones).")
    if time.time() < tok["expires_at"] - 300:
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise RuntimeError("El token de TikTok expiró. Vuelve a conectar TikTok.")
    r = requests.post(f"{API}/v2/oauth/token/", data={
        "client_key": S.get_secret("tiktok_client_key"),
        "client_secret": S.get_secret("tiktok_client_secret"),
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"No se pudo renovar el token de TikTok: {data}. Vuelve a conectar.")
    _store_token(data)
    return data["access_token"]


def _headers():
    return {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8"}


def user_name() -> str | None:
    try:
        r = requests.get(f"{API}/v2/user/info/", params={"fields": "display_name"}, headers=_headers(), timeout=20)
        return r.json().get("data", {}).get("user", {}).get("display_name")
    except Exception:
        return None


def _chunks(size: int) -> tuple[int, int]:
    if size <= MAX_SINGLE:
        return size, 1
    return CHUNK, size // CHUNK  # el último trozo absorbe el resto


def upload(video: Path, caption: str, mode: str, privacy: str, on_progress: Callable[[float], None]) -> dict:
    size = video.stat().st_size
    chunk_size, count = _chunks(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}
    h = _headers()
    note = ""
    if mode == "direct":
        info = requests.post(f"{API}/v2/post/publish/creator_info/query/", headers=h, timeout=30).json()
        options = info.get("data", {}).get("privacy_level_options", [])
        level = privacy if privacy in options else ("SELF_ONLY" if "SELF_ONLY" in options else (options or ["SELF_ONLY"])[0])
        if level != privacy:
            note = f"TikTok solo permitió privacidad «{level}» (las apps sin auditoría publican en privado)."
        body = {"post_info": {"title": caption[:2200], "privacy_level": level, "disable_comment": False,
                              "disable_duet": False, "disable_stitch": False},
                "source_info": source}
        url = f"{API}/v2/post/publish/video/init/"
    else:
        body = {"source_info": source}
        url = f"{API}/v2/post/publish/inbox/video/init/"
        note = "Enviado a la bandeja de TikTok: termina la publicación desde la app."
    r = requests.post(url, json=body, headers=h, timeout=30)
    data = r.json()
    if r.status_code != 200 or data.get("error", {}).get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok init: {r.status_code} {data.get('error')}")
    upload_url, publish_id = data["data"]["upload_url"], data["data"]["publish_id"]

    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk_size
            end = size - 1 if i == count - 1 else start + chunk_size - 1
            f.seek(start)
            payload = f.read(end - start + 1)
            pr = requests.put(upload_url, data=payload, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(payload)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if pr.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload trozo {i+1}/{count}: {pr.status_code} {pr.text[:200]}")
            on_progress((i + 1) / count)

    status = "PROCESSING"
    for _ in range(20):
        time.sleep(3)
        st = requests.post(f"{API}/v2/post/publish/status/fetch/", json={"publish_id": publish_id},
                           headers=_headers(), timeout=30).json()
        status = st.get("data", {}).get("status", status)
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"):
            break
    if status == "FAILED":
        raise RuntimeError(f"TikTok marcó la publicación como fallida: {st.get('data', {}).get('fail_reason')}")
    return {"platform_id": publish_id, "url": "", "privacy": privacy if mode == "direct" else "inbox",
            "note": note, "status": status}
