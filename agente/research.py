"""Investigación de tendencias en YouTube.

Busca videos RECIENTES del nicho y los puntúa con métricas normalizadas:
  - velocidad: log(vistas por día desde la publicación)
  - engagement: (likes + comentarios) / vistas
El puntaje combina ambos como z-scores, así ninguna magnitud absoluta domina.
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import datetime, timedelta, timezone

from . import settings as S
from .events import Run

_ISO_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration_seconds(s: str) -> int:
    m = _ISO_DUR.fullmatch(s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def _z(values):
    if len(values) < 2:
        return [0.0] * len(values)
    mu = statistics.fmean(values)
    sd = statistics.pstdev(values) or 1.0
    return [(v - mu) / sd for v in values]


def research(run: Run, cfg: dict) -> dict:
    sid = "research"
    api_key = S.get_secret("youtube_api_key")
    content = cfg["content"]
    if not api_key:
        run.warn("Sin YouTube API key: se omite la investigación; el guion se basará solo en el nicho.", sid)
        return {"niche": content["niche"], "videos": []}

    from googleapiclient.discovery import build

    yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    since = datetime.now(timezone.utc) - timedelta(days=int(content["research_days"]))
    params = dict(
        q=content["niche"], part="id", type="video", order="viewCount", maxResults=25,
        publishedAfter=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        relevanceLanguage=content["language"],
    )
    if content.get("region_code"):
        params["regionCode"] = content["region_code"]
    run.step_progress(sid, 0.2, f"Buscando «{content['niche']}» (últimos {content['research_days']} días)")
    search = yt.search().list(**params).execute()
    ids = [it["id"]["videoId"] for it in search.get("items", [])]
    if not ids:
        run.warn("La búsqueda no devolvió videos recientes.", sid)
        return {"niche": content["niche"], "videos": []}

    run.step_progress(sid, 0.5, f"Analizando {len(ids)} videos")
    resp = yt.videos().list(part="statistics,contentDetails,snippet", id=",".join(ids)).execute()
    now = datetime.now(timezone.utc)
    videos = []
    for v in resp.get("items", []):
        st = v.get("statistics", {})
        views = int(st.get("viewCount", 0))
        likes = int(st.get("likeCount", 0))
        comments = int(st.get("commentCount", 0))
        published = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        age_days = max((now - published).total_seconds() / 86400, 0.5)
        videos.append({
            "video_id": v["id"],
            "title": v["snippet"]["title"],
            "channel": v["snippet"].get("channelTitle", ""),
            "views": views, "likes": likes, "comments": comments,
            "duration_s": iso_duration_seconds(v["contentDetails"].get("duration", "")),
            "age_days": round(age_days, 1),
            "views_per_day": round(views / age_days, 1),
            "engagement": round((likes + comments) / views, 4) if views else 0.0,
        })

    zv = _z([math.log1p(v["views_per_day"]) for v in videos])
    ze = _z([v["engagement"] for v in videos])
    for v, a, b in zip(videos, zv, ze):
        v["score"] = round(0.65 * a + 0.35 * b, 3)
    videos.sort(key=lambda v: v["score"], reverse=True)

    top = videos[0] if videos else None
    if top:
        run.info(f"Tendencia líder: «{top['title']}» ({top['views_per_day']:.0f} vistas/día, "
                 f"engagement {top['engagement']*100:.1f}%)", sid)
    return {"niche": content["niche"], "videos": videos}
