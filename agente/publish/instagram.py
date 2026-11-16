"""Instagram Reels vía Graph API, con el mismo token de página de Facebook.

Requisitos: cuenta de Instagram profesional (empresa o creador) vinculada a la página de Facebook,
y un token con los permisos instagram_basic e instagram_content_publish (además de los de la página).
Subida local «resumable»: crear contenedor → enviar el archivo a rupload → esperar → publicar.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import requests

from .. import settings as S
from . import facebook

GRAPH = "https://graph.facebook.com"
PERMS_HINT = ("Revisa que tu Instagram sea profesional, esté vinculado a la página de Facebook y que el token "
              "tenga los permisos instagram_basic e instagram_content_publish.")


META_HINT = ("Es un fallo intermitente del lado de Meta (el mismo tipo de video a veces sube y a veces no). Vuelve a "
             "intentar más tarde con «Publicar» o súbelo desde la app de Instagram; el video en sí está bien.")


class UncertainPublish(RuntimeError):
    """La orden de publicar no tuvo respuesta: puede que el Reel sí se haya publicado (no reintentar por otra vía)."""


def _check(data: dict, what: str) -> dict:
    if isinstance(data, dict) and "error" in data:
        msg = data["error"].get("message", "")
        if data["error"].get("code") in (10, 200, 190) or "permission" in msg.lower():
            raise RuntimeError(f"Instagram ({what}): sin permiso. {PERMS_HINT}")
        raise RuntimeError(f"Instagram ({what}): {msg[:200]}")
    return data


def account(version: str) -> dict:
    """{"id", "username"} de la cuenta de Instagram vinculada a la página."""
    token = facebook._token()
    page = facebook.page_info(version)
    data = _check(requests.get(f"{GRAPH}/{version}/{page['id']}", timeout=30, params={
        "fields": "instagram_business_account{id,username}", "access_token": token}).json(), "cuenta")
    ig = data.get("instagram_business_account")
    if not ig:
        raise RuntimeError("La página de Facebook no tiene una cuenta de Instagram profesional vinculada. " + PERMS_HINT)
    return ig


def upload_reel(video: Path, caption: str, version: str, on_progress: Callable[[float], None]) -> dict:
    token = facebook._token()
    ig = account(version)
    c = _check(requests.post(f"{GRAPH}/{version}/{ig['id']}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "access_token": token}).json(), "crear contenedor")
    cid, uri = c["id"], c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{version}/{c['id']}"
    on_progress(0.1)
    with open(video, "rb") as f:
        up = requests.post(uri, data=f, timeout=1800, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(video.stat().st_size)}).json()
    if not up.get("success"):
        kind = (up.get("debug_info") or {}).get("type", "")
        raise RuntimeError(f"Instagram rechazó el video al procesarlo ({kind or str(up)[:120]}). " + META_HINT)
    on_progress(0.6)
    # Instagram procesa el video antes de poder publicarlo
    t0 = time.time()
    while True:
        st = _check(requests.get(f"{GRAPH}/{version}/{cid}", timeout=30, params={
            "fields": "status_code,status", "access_token": token}).json(), "estado")
        code = st.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar el video ({st.get('status', code)}). " + META_HINT)
        if time.time() - t0 > 600:
            raise RuntimeError("Instagram tardó más de 10 minutos en procesar el video.")
        on_progress(min(0.9, 0.6 + (time.time() - t0) / 600 * 0.3))
        time.sleep(5)
    try:
        answer = requests.post(f"{GRAPH}/{version}/{ig['id']}/media_publish", timeout=60, data={
            "creation_id": cid, "access_token": token}).json()
    except (requests.RequestException, ValueError) as e:
        raise UncertainPublish(f"Instagram no respondió a la orden de publicar ({e}). Revisa tu perfil antes de "
                               "reintentar: puede que el Reel sí se haya publicado.")
    pub = _check(answer, "publicar")
    media_id = pub["id"]
    link = ""
    try:
        link = requests.get(f"{GRAPH}/{version}/{media_id}", timeout=30, params={
            "fields": "permalink", "access_token": token}).json().get("permalink", "")
    except Exception:
        pass
    on_progress(1.0)
    return {"platform_id": media_id, "url": link or f"https://www.instagram.com/{ig.get('username', '')}",
            "privacy": "public", "note": ""}


MISSING: set[str] = set()  # permisos que faltaron en la última lectura de métricas


def media_id_for(shortcode: str, version: str) -> str | None:
    """Id de la API de una publicación hecha por navegador (que solo da el código del enlace /reel/<code>/)."""
    try:
        token = facebook._token()
        ig = account(version)
        data = requests.get(f"{GRAPH}/{version}/{ig['id']}/media", timeout=30, params={
            "fields": "id,permalink", "limit": 25, "access_token": token}).json().get("data", [])
        return next((m["id"] for m in data if f"/{shortcode}/" in (m.get("permalink") or "")), None)
    except Exception:
        return None


def fetch_stats(ids: list[str], version: str) -> dict[str, dict]:
    token = S.get_secret("facebook_page_token")
    if not token:
        return {}
    out = {}
    for mid in ids:
        try:
            base = requests.get(f"{GRAPH}/{version}/{mid}", timeout=30, params={
                "fields": "like_count,comments_count", "access_token": token}).json()
            if "error" in base:
                continue
            views = None  # desconocidas: sin el permiso de estadísticas Meta no las entrega (no es lo mismo que 0)
            ins = requests.get(f"{GRAPH}/{version}/{mid}/insights", timeout=30, params={
                "metric": "views", "access_token": token}).json()
            if "error" in ins:
                MISSING.add("instagram_manage_insights")
            for m in ins.get("data", []):
                views = max(views or 0, int((m.get("values") or [{}])[0].get("value", 0) or 0))
            out[mid] = {"views": views, "likes": base.get("like_count", 0), "comments": base.get("comments_count", 0)}
        except Exception:
            continue
    return out
