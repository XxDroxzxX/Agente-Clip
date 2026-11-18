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


HASHTAG = re.compile(r"#([^\s#.,;:!?¡¿()\[\]\"'«»]{2,40})", re.UNICODE)
GENERIC_TAGS = {"shorts", "short", "youtube", "youtubeshorts", "viral", "video", "subscribe", "fyp", "foryou",
                "parati", "foryoupage", "fy", "trending", "tiktok", "reels"}


LATIN_LANGS = {"en", "es", "pt", "fr", "de", "it", "nl", "pl", "tr", "id", "vi"}


def same_script(title: str, lang: str) -> bool:
    """Para idiomas de alfabeto latino, descarta títulos escritos mayormente en otro alfabeto (malayalam, coreano…)."""
    if lang not in LATIN_LANGS:
        return True
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return True
    other = sum(1 for c in letters if ord(c) > 0x24F)  # fuera de latín básico y extendido
    return other / len(letters) < 0.3


def top_hashtags(videos: list[dict], n: int = 12) -> list[str]:
    """Hashtags más usados por los videos en tendencia del nicho, pesados por su rendimiento (vistas/día).
    Se excluyen los genéricos (#shorts, #fyp…): esos los agrega la app según la plataforma."""
    score: dict[str, float] = {}
    shown: dict[str, str] = {}
    for v in videos:
        weight = math.log1p(v.get("views_per_day", 0)) + 1
        seen = set()
        for raw in v.get("hashtags", []):
            key = raw.lower()
            if key in GENERIC_TAGS or key in seen or key.isdigit():
                continue
            seen.add(key)
            score[key] = score.get(key, 0) + weight
            shown.setdefault(key, raw)
    ranked = sorted(score, key=lambda k: score[k], reverse=True)
    return [f"#{shown[k]}" for k in ranked if score[k] > 0][:n]


def search_query(cfg: dict, log=None) -> str:
    """Término de búsqueda en el idioma de la audiencia. Con el nicho escrito en otro idioma («Historias de terror»
    para un canal en inglés), YouTube devolvía tendencias de otro público. Manual (content.search_query) o traducido
    una vez con Gemini y guardado en caché."""
    import json
    from .paths import CACHE_DIR
    c = cfg["content"]
    manual = (c.get("search_query") or "").strip()
    if manual:
        return manual
    niche, lang = c["niche"].strip(), c["language"]
    cache = CACHE_DIR / "search_query.json"
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        saved = {}
    key = f"{lang}|{niche}"
    if key in saved:
        return saved[key]
    if not S.get_secret("gemini_api_key"):
        return niche
    try:
        from . import gemini
        from .catalog import LANGUAGES
        text, _ = gemini.generate(gemini.chain(None, gemini.LITE_FIRST),
                                  f"Convert this YouTube search topic into the phrase a {LANGUAGES[lang]}-speaking viewer "
                                  f"would type to find such videos, in {LANGUAGES[lang]} (language code {lang}). If it is "
                                  f"already right, return it unchanged. Output only the phrase, 2-5 words.\nTopic: {niche}",
                                  thinking="low", timeout=60, max_tokens=200)
        q = text.strip().strip('"«»').splitlines()[0][:80] or niche
    except Exception:
        return niche
    saved[key] = q
    cache.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    if log and q.lower() != niche.lower():
        log(f"Búsqueda de tendencias en el idioma de la audiencia: «{q}» (nicho: «{niche}»).")
    return q


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
    query = search_query(cfg, lambda m: run.info(m, sid))
    params = dict(
        q=query, part="id", type="video", order="viewCount", maxResults=25,
        publishedAfter=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        relevanceLanguage=content["language"],
    )
    if content.get("region_code"):
        params["regionCode"] = content["region_code"]
    run.step_progress(sid, 0.2, f"Buscando «{query}» (últimos {content['research_days']} días)")
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
            "hashtags": HASHTAG.findall(v["snippet"]["title"] + " " + v["snippet"].get("description", ""))
                        + [t.replace(" ", "") for t in v["snippet"].get("tags", [])[:15]],
        })

    # relevanceLanguage solo ordena, no filtra: salían tendencias en francés y hashtags de cine malayalam en un
    # canal en inglés. Se quitan los videos cuyo idioma declarado es otro (los sin idioma declarado se quedan).
    langs = {v["id"]: (v["snippet"].get("defaultAudioLanguage") or v["snippet"].get("defaultLanguage") or "")
             .lower().split("-")[0] for v in resp.get("items", [])}
    same = [v for v in videos if langs.get(v["video_id"]) in ("", content["language"])
            and same_script(v["title"], content["language"])]
    if len(same) >= 5 and len(same) < len(videos):
        run.info(f"Se descartaron {len(videos) - len(same)} videos en otros idiomas.", sid)
        videos = same

    zv = _z([math.log1p(v["views_per_day"]) for v in videos])
    ze = _z([v["engagement"] for v in videos])
    for v, a, b in zip(videos, zv, ze):
        v["score"] = round(0.65 * a + 0.35 * b, 3)
    videos.sort(key=lambda v: v["score"], reverse=True)

    top = videos[0] if videos else None
    if top:
        run.info(f"Tendencia líder: «{top['title']}» ({top['views_per_day']:.0f} vistas/día, "
                 f"engagement {top['engagement']*100:.1f}%)", sid)
    tags = top_hashtags(videos)
    if tags:
        run.info(f"Hashtags más usados en el nicho: {' '.join(tags[:8])}", sid)
    return {"niche": content["niche"], "videos": videos, "top_hashtags": tags}
