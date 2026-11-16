"""Facebook: video de página (largo) y Reels (vertical) vía Graph API."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import time

import requests

from .. import settings as S


def _token() -> str:
    t = S.get_secret("facebook_page_token")
    if not t:
        raise RuntimeError("Falta el Facebook Page access token.")
    return t


def page_info(version: str) -> dict:
    r = requests.get(f"https://graph.facebook.com/{version}/me", params={"fields": "id,name", "access_token": _token()},
                     timeout=30)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Facebook: {data['error'].get('message')}")
    return data


def _granted_pages(token: str, version: str) -> list[dict]:
    """Páginas autorizadas en el token aunque /me/accounts venga vacío: pasa con las páginas administradas desde un
    portafolio comercial (Meta Business Suite). El token trae sus ids en granular_scopes."""
    try:
        dbg = requests.get("https://graph.facebook.com/debug_token", timeout=20,
                           params={"input_token": token, "access_token": token}).json().get("data", {})
        if dbg.get("type") != "USER":
            return []
        ids = []
        for sc in dbg.get("granular_scopes", []):
            if sc.get("scope") in ("pages_manage_posts", "pages_show_list", "pages_read_engagement"):
                ids += [i for i in sc.get("target_ids", []) if i not in ids]
        pages = []
        for pid in ids:
            p = requests.get(f"https://graph.facebook.com/{version}/{pid}", timeout=20,
                             params={"fields": "name,access_token", "access_token": token}).json()
            if p.get("access_token"):
                pages.append(p)
        return pages
    except Exception:
        return []


def normalize_token(token: str, version: str) -> tuple[str, str]:
    """Si pegan un token de USUARIO, obtiene el token de la página (que no vence si el de usuario es de larga
    duración). Devuelve (token_a_guardar, aviso para el usuario)."""
    try:
        r = requests.get(f"https://graph.facebook.com/{version}/me/accounts", timeout=30,
                         params={"fields": "name,access_token", "access_token": token}).json()
    except Exception:
        return token, ""
    pages = r.get("data") if isinstance(r, dict) else None
    if not pages and isinstance(r, dict) and "error" not in r:
        pages = _granted_pages(token, version)
    note = ""
    if pages:  # era un token de usuario
        page = pages[0]
        token = page["access_token"]
        note = f"Se detectó un token de usuario: se guardó el token de la página «{page.get('name')}»."
        if len(pages) > 1:
            note += f" (Tienes {len(pages)} páginas; se usa la primera.)"
    elif isinstance(r, dict) and r.get("error", {}).get("code") == 190:
        raise RuntimeError("Ese token de Facebook ya venció o no es válido. Genera uno nuevo (ver «¿Cómo lo obtengo?»).")
    try:
        info = requests.get("https://graph.facebook.com/oauth/access_token_info", timeout=20,
                            params={"access_token": token}).json()
        exp = info.get("expires_in")
        if exp and int(exp) < 7 * 86400:
            hours = int(exp) // 3600
            note += (f" Atención: este token vence en ~{hours} h. Para uno permanente, extiende primero el token de "
                     "usuario en el Depurador de tokens y pégalo aquí (ver «¿Cómo lo obtengo?»).")
    except Exception:
        pass
    return token, note.strip()


def _json(r: requests.Response, what: str) -> dict:
    """Respuesta de la Graph API. Si Facebook devuelve una página de error (no JSON), lo explica en vez de fallar
    con «Expecting value»."""
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"Facebook ({what}) respondió con un error {r.status_code} sin detalles. Suele ser un corte "
                           "temporal: vuelve a intentar con «Publicar».")
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Facebook ({what}): {data['error'].get('message')}")
    return data


def upload_video(video: Path, title: str, description: str, version: str, on_progress: Callable[[float], None],
                 published: bool = True) -> dict:
    """Video de página por partes (subida reanudable): un archivo grande en una sola petición termina cortado."""
    token = _token()
    page = page_info(version)
    base = f"https://graph-video.facebook.com/{version}/{page['id']}/videos"
    size = video.stat().st_size
    st = _json(requests.post(base, timeout=60, data={"upload_phase": "start", "file_size": size,
                                                     "access_token": token}), "inicio")
    session, vid = st["upload_session_id"], st["video_id"]
    start, end = int(st["start_offset"]), int(st["end_offset"])
    with open(video, "rb") as f:
        while start < end:
            f.seek(start)
            chunk = f.read(end - start)
            for attempt in range(3):  # cada parte se reintenta: una sola caída no arruina toda la subida
                try:
                    st = _json(requests.post(base, timeout=300, data={
                        "upload_phase": "transfer", "upload_session_id": session, "start_offset": start,
                        "access_token": token}, files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")}),
                        "subida")
                    break
                except (RuntimeError, requests.RequestException):
                    if attempt == 2:
                        raise
                    time.sleep(5 * (attempt + 1))
            start, end = int(st["start_offset"]), int(st["end_offset"])
            on_progress(0.05 + 0.85 * start / size)
    fin = _json(requests.post(base, timeout=120, data={
        "upload_phase": "finish", "upload_session_id": session, "title": title[:250], "description": description,
        "published": "true" if published else "false", "access_token": token}), "publicación")
    if not fin.get("success"):
        raise RuntimeError(f"Facebook no confirmó la publicación del video: {fin}")
    on_progress(1.0)
    return {"platform_id": vid, "url": f"https://www.facebook.com/{page['id']}/videos/{vid}", "privacy": "public", "note": ""}


def upload_reel(video: Path, description: str, version: str, on_progress: Callable[[float], None]) -> dict:
    token = _token()
    page = page_info(version)
    base = f"https://graph.facebook.com/{version}/{page['id']}/video_reels"
    start = requests.post(base, data={"upload_phase": "start", "access_token": token}, timeout=30).json()
    if "video_id" not in start:
        raise RuntimeError(f"Facebook Reels (inicio): {start.get('error', start)}")
    vid = start["video_id"]
    on_progress(0.2)
    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(f"https://rupload.facebook.com/video-upload/{version}/{vid}", data=f, timeout=1800,
                           headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}).json()
    if not up.get("success"):
        raise RuntimeError(f"Facebook Reels (subida): {up}")
    on_progress(0.8)
    fin = requests.post(base, data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                    "description": description, "access_token": token}, timeout=60).json()
    if not fin.get("success"):
        raise RuntimeError(f"Facebook Reels (publicación): {fin.get('error', fin)}")
    on_progress(1.0)
    return {"platform_id": vid, "url": f"https://www.facebook.com/reel/{vid}", "privacy": "public", "note": ""}


def fetch_stats(ids: list[str], version: str) -> dict[str, dict]:
    token = S.get_secret("facebook_page_token")
    if not token:
        return {}
    out = {}
    for vid in ids:
        try:
            base = requests.get(f"https://graph.facebook.com/{version}/{vid}", params={
                "fields": "likes.summary(true).limit(0),comments.summary(true).limit(0)",
                "access_token": token}, timeout=30).json()
            if "error" in base:
                continue
            views = 0
            ins = requests.get(f"https://graph.facebook.com/{version}/{vid}/video_insights", params={
                "metric": "total_video_views,fb_reels_total_plays", "access_token": token}, timeout=30).json()
            for m in ins.get("data", []):
                vals = m.get("values") or [{}]
                views = max(views, int(vals[0].get("value", 0) or 0))
            out[vid] = {
                "views": views,
                "likes": base.get("likes", {}).get("summary", {}).get("total_count", 0),
                "comments": base.get("comments", {}).get("summary", {}).get("total_count", 0),
            }
        except Exception:
            continue
    return out
