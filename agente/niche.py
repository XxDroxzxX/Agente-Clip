"""Investigación de nicho para quien empieza: qué temas tienen demanda y espacio, y con qué configuración atacarlos.

1. Una IA propone nichos candidatos a partir de los intereses del usuario (o los más prometedores si no los da).
2. Cada nicho se mide con datos reales de YouTube: demanda (vistas/día), interacción, oportunidad (vistas frente a
   suscriptores del canal: si canales pequeños logran muchas vistas, hay espacio) y peso de los Shorts.
3. Con esas cifras la IA recomienda la configuración de la app para cada nicho, que el usuario puede aplicar.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel, Field

from . import catalog
from . import settings as S
from .research import iso_duration_seconds

Log = Callable[[str], None]

SYSTEM = ("Eres estratega de contenido para YouTube Shorts, TikTok, Reels y videos largos. Respondes en español, con "
          "criterio práctico y sin exagerar. No inventes cifras: usa solo las que te den.")


class Candidate(BaseModel):
    niche: str = Field(description="Nombre corto del nicho en español (2-5 palabras).")
    query: str = Field(description="Búsqueda en YouTube, en el idioma de la audiencia, 2-5 palabras.")
    audience: str = Field(description="A quién le habla, en una frase corta en español.")


class Candidates(BaseModel):
    candidates: list[Candidate]


class Recommendation(BaseModel):
    niche: str = Field(description="El mismo nombre de nicho recibido.")
    verdict: Literal["recomendado", "posible", "difícil"]
    why: str = Field(description="Por qué, en 2-3 frases, citando las cifras recibidas.")
    content_ideas: list[str] = Field(description="3 ideas de videos concretas para empezar.")
    hook_styles: list[str] = Field(description="2 estilos de gancho de la lista dada que mejor encajan.")
    reading_style: int = Field(description="Índice (0-based) del estilo de lectura de la lista dada.")
    visual_style: int = Field(description="Índice (0-based) del estilo visual de la lista dada.")
    visual_provider: Literal["pexels", "comfyui"] = Field(
        description="pexels si el nicho se cuenta bien con clips reales de stock; comfyui si necesita escenas "
                    "imposibles de filmar (personajes, fantasía, historias).")
    shorts_count: int = Field(description="Shorts por día recomendados (1-3).")
    long_enabled: bool = Field(description="Si conviene también un video largo diario.")
    long_minutes: int = Field(description="Minutos del video largo (3-10) si aplica.")
    voice_rate: Literal["-10%", "+0%", "+6%", "+12%"]
    music: bool
    tips: list[str] = Field(description="2-3 consejos concretos para crecer en este nicho.")


class Recommendations(BaseModel):
    items: list[Recommendation]


def _llm(cfg: dict, prompt: str, model: type[BaseModel], log: Log, max_tokens: int = 6000):
    from . import vision
    prov = "gemini" if S.get_secret("gemini_api_key") else "claude" if S.get_secret("anthropic_api_key") else None
    if not prov:
        raise RuntimeError("Hace falta la Gemini API key (gratis) o la de Claude para investigar nichos. "
                           "Agrégala en Configuración → Credenciales.")
    return vision._call(prov, cfg, SYSTEM, [prompt], model, lambda m, lvl="info": log(m), max_tokens)


def measure(yt, query: str, lang: str, region: str, days: int = 30) -> dict:
    """Cifras reales del nicho en YouTube (unas 105 unidades de cuota)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    params = dict(q=query, part="id", type="video", order="viewCount", maxResults=20,
                  publishedAfter=since.strftime("%Y-%m-%dT%H:%M:%SZ"), relevanceLanguage=lang)
    if region:
        params["regionCode"] = region
    ids = [it["id"]["videoId"] for it in yt.search().list(**params).execute().get("items", [])]
    if not ids:
        return {"videos": 0}
    items = yt.videos().list(part="statistics,contentDetails,snippet", id=",".join(ids)).execute().get("items", [])
    chans = list({v["snippet"]["channelId"] for v in items})
    subs = {}
    for i in range(0, len(chans), 50):
        for c in yt.channels().list(part="statistics", id=",".join(chans[i:i + 50])).execute().get("items", []):
            st = c.get("statistics", {})
            if not st.get("hiddenSubscriberCount"):
                subs[c["id"]] = int(st.get("subscriberCount", 0))
    now = datetime.now(timezone.utc)
    vpd, eng, ratio, shorts = [], [], [], 0
    for v in items:
        st = v.get("statistics", {})
        views = int(st.get("viewCount", 0))
        age = max((now - datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))).days, 1)
        vpd.append(views / age)
        if views:
            eng.append((int(st.get("likeCount", 0)) + int(st.get("commentCount", 0))) / views)
        s = subs.get(v["snippet"]["channelId"])
        if s:
            ratio.append(views / max(s, 100))
        if iso_duration_seconds(v["contentDetails"].get("duration", "")) <= 180:
            shorts += 1
    return {
        "videos": len(items),
        "views_per_day": round(statistics.median(vpd)) if vpd else 0,
        "engagement_pct": round(100 * statistics.median(eng), 2) if eng else 0.0,
        "opportunity": round(statistics.median(ratio), 2) if ratio else 0.0,  # vistas por suscriptor del canal
        "small_channels_pct": round(100 * sum(1 for c in subs.values() if c < 10000) / max(len(subs), 1)),
        "shorts_pct": round(100 * shorts / len(items)),
        "top_titles": [v["snippet"]["title"] for v in sorted(
            items, key=lambda v: int(v.get("statistics", {}).get("viewCount", 0)), reverse=True)[:3]],
    }


def score(m: dict) -> float:
    """Puntaje 0-100: demanda, interacción y oportunidad para canales nuevos."""
    if not m.get("videos"):
        return 0.0
    demand = min(1.0, math.log10(1 + m["views_per_day"]) / 5)          # 100k vistas/día ≈ 1
    eng = min(1.0, m["engagement_pct"] / 6)                            # 6 % ≈ 1
    opp = min(1.0, math.log10(1 + m["opportunity"]) / 2)               # 100 vistas por suscriptor ≈ 1
    small = m["small_channels_pct"] / 100
    return round(100 * (0.35 * demand + 0.2 * eng + 0.3 * opp + 0.15 * small), 1)


def research(cfg: dict, interests: str, lang: str, region: str, log: Log = print, n: int = 6) -> dict:
    """Devuelve {"niches": [{niche, query, audience, metrics, score, recommendation, settings}], "quota": unidades}."""
    key = S.get_secret("youtube_api_key")
    if not key:
        raise RuntimeError("Hace falta la YouTube Data API key (gratis) para medir los nichos. "
                           "Agrégala en Configuración → Credenciales.")
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", developerKey=key, cache_discovery=False)
    lang_name = catalog.LANGUAGES.get(lang, lang)
    country = dict(catalog.REGIONS).get(region, "todo el mundo")
    log("Pensando nichos candidatos…")
    cands = _llm(cfg, (
        f"Intereses del usuario: {interests.strip() or '(no los dio: propone los nichos con más potencial para un canal nuevo de videos narrados)'}\n"
        f"Audiencia: habla {lang_name}, país: {country}.\n"
        f"Propón {n} nichos distintos para un canal NUEVO de videos narrados con voz en off, clips de stock o video IA "
        f"y subtítulos (sin mostrar la cara). Variados entre sí, específicos (no «entretenimiento»), y que se puedan "
        f"producir todos los días. Para cada uno, la búsqueda que haría esa audiencia en YouTube, en {lang_name}."),
        Candidates, log).candidates[:n]
    rows = []
    for i, c in enumerate(cands):
        log(f"Midiendo en YouTube {i + 1}/{len(cands)}: «{c.query}»")
        try:
            m = measure(yt, c.query, lang, region)
        except Exception as e:
            log(f"No se pudo medir «{c.query}» ({str(e)[:120]}).")
            m = {"videos": 0}
        rows.append({"niche": c.niche, "query": c.query, "audience": c.audience, "metrics": m, "score": score(m)})
    rows.sort(key=lambda r: r["score"], reverse=True)

    log("Armando recomendaciones…")
    reading = [label for _, label in catalog.READING_STYLES]
    visual = [label for _, label in catalog.VISUAL_STYLES]
    from .learning import HOOK_STYLES
    data = "\n".join(f"- {r['niche']} (búsqueda «{r['query']}», puntaje {r['score']}/100): {r['metrics']}" for r in rows)
    recs = _llm(cfg, (
        f"Cifras reales de YouTube (últimos 30 días, {country}, {lang_name}) por nicho:\n{data}\n\n"
        "views_per_day = mediana de vistas diarias de los videos más vistos; engagement_pct = (me gusta + comentarios) "
        "/ vistas; opportunity = vistas por suscriptor del canal (alto = canales pequeños también despegan); "
        "small_channels_pct = % de canales con menos de 10 mil suscriptores; shorts_pct = % de videos de 3 min o menos.\n\n"
        f"Estilos de gancho válidos: {', '.join(HOOK_STYLES)}.\n"
        f"Estilos de lectura (índice: nombre): {dict(enumerate(reading))}.\n"
        f"Estilos visuales (índice: nombre): {dict(enumerate(visual))}.\n\n"
        "Para cada nicho, da tu veredicto para un canal nuevo y la configuración recomendada de la app."),
        Recommendations, log, 8000).items
    by_name = {r.niche.strip().lower(): r for r in recs}
    for r in rows:
        rec = by_name.get(r["niche"].strip().lower())
        if rec:
            r["recommendation"] = rec.model_dump()
            r["settings"] = to_settings(rec, r, lang, region)
    return {"niches": rows, "quota": 105 * len(rows)}


def to_settings(rec, row: dict, lang: str, region: str) -> dict:
    """Recomendación → cambios de configuración válidos (los revisa settings.validate al guardar)."""
    pick = lambda lst, i, d=0: lst[i][0] if 0 <= i < len(lst) else lst[d][0]  # noqa: E731
    return {
        "content": {"niche": row["niche"], "audience": row["audience"], "language": lang, "region_code": region,
                    "search_query": row["query"]},
        "voice": {"engine": "gemini", "gemini_style": pick(catalog.READING_STYLES, rec.reading_style),
                  "rate": rec.voice_rate, "name": catalog.DEFAULT_VOICE.get(lang, catalog.DEFAULT_VOICE["es"])},
        "video": {"visual_provider": rec.visual_provider, "ai_style": pick(catalog.VISUAL_STYLES, rec.visual_style),
                  "shorts_count": max(1, min(3, rec.shorts_count)), "long_enabled": rec.long_enabled,
                  "long_minutes": max(3, min(10, rec.long_minutes)), "music": rec.music},
    }
