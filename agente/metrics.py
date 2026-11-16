"""Recolección de métricas de publicaciones con antigüedad suficiente y actualización del aprendizaje."""
from __future__ import annotations

import time

from . import learning
from .events import Run
from .publish import facebook, instagram, youtube


def collect(run: Run, cfg: dict) -> dict:
    sid = "metrics"
    m = cfg["metrics"]
    now = time.time()
    hist = learning.load_history()
    min_age, max_age = m["min_age_hours"] * 3600, m["max_age_days"] * 86400
    # se mide todo lo publicado en los últimos max_age días (no solo lo de hoy)
    due = [h for h in hist if h.get("platform_id") and now - h["published_at"] <= max_age]
    by_platform: dict[str, list] = {}
    for h in due:
        by_platform.setdefault(h["platform"], []).append(h)

    rows = []
    if by_platform.get("youtube"):
        run.step_progress(sid, 0.3, f"YouTube: {len(by_platform['youtube'])} publicaciones")
        stats = youtube.fetch_stats([h["platform_id"] for h in by_platform["youtube"]
                                     if not str(h["platform_id"]).startswith("yt-browser")])
        for h in by_platform["youtube"]:
            if h["platform_id"] in stats:
                rows.append({"ts": now, "platform": "youtube", "platform_id": h["platform_id"],
                             "age_hours": round((now - h["published_at"]) / 3600, 1), **stats[h["platform_id"]]})
    for name, label, fetch, prog in (("facebook", "Facebook", facebook.fetch_stats, 0.55),
                                     ("instagram", "Instagram", instagram.fetch_stats, 0.75)):
        if not by_platform.get(name):
            continue
        run.step_progress(sid, prog, f"{label}: {len(by_platform[name])} publicaciones")
        mod = facebook if name == "facebook" else instagram
        mod.MISSING.clear()
        stats = fetch([h["platform_id"] for h in by_platform[name]], cfg["publish"]["facebook_graph_version"])
        if mod.MISSING:
            run.warn(f"{label}: no se pudieron leer las vistas porque al token le falta el permiso "
                     f"{', '.join(sorted(mod.MISSING))}. Genera el token de nuevo incluyéndolo (Explorador de la Graph "
                     f"API) y guárdalo en Credenciales; mientras tanto, {label} no cuenta para el aprendizaje.", sid)
        unresolved = [h for h in by_platform[name] if h["platform_id"] not in stats]
        if unresolved and name == "instagram":
            run.warn(f"Instagram: {len(unresolved)} publicación(es) sin métricas (id no reconocido por la API).", sid)
        for h in by_platform[name]:
            if h["platform_id"] in stats and stats[h["platform_id"]]["views"] is not None:
                rows.append({"ts": now, "platform": name, "platform_id": h["platform_id"],
                             "age_hours": round((now - h["published_at"]) / 3600, 1), **stats[h["platform_id"]]})
    if by_platform.get("tiktok"):
        run.info("TikTok: la Content Posting API no expone métricas; se omiten.", sid)

    if rows:
        learning.append_snapshots(rows)
    mature = sum(1 for r in rows if r["age_hours"] * 3600 >= min_age)
    run.info(f"{len(rows)} métricas registradas ({mature} con más de {m['min_age_hours']} h).", sid)

    result = learning.recompute(m["min_age_hours"])
    if result["styles"]:
        best = max(result["styles"].items(), key=lambda kv: kv[1]["mean"])
        run.info(f"Aprendizaje: mejor estilo de gancho «{best[0]}» ({best[1]['mean']:+.2f}, n={best[1]['n']}).", sid)
    else:
        run.info("Aprendizaje: aún no hay publicaciones con métricas maduras.", sid)
    return result
