"""Recolección de métricas de publicaciones con antigüedad suficiente y actualización del aprendizaje."""
from __future__ import annotations

import time

from . import learning
from .events import Run
from .publish import facebook, youtube


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
        stats = youtube.fetch_stats([h["platform_id"] for h in by_platform["youtube"]])
        for h in by_platform["youtube"]:
            if h["platform_id"] in stats:
                rows.append({"ts": now, "platform": "youtube", "platform_id": h["platform_id"],
                             "age_hours": round((now - h["published_at"]) / 3600, 1), **stats[h["platform_id"]]})
    if by_platform.get("facebook"):
        run.step_progress(sid, 0.6, f"Facebook: {len(by_platform['facebook'])} publicaciones")
        stats = facebook.fetch_stats([h["platform_id"] for h in by_platform["facebook"]],
                                     cfg["publish"]["facebook_graph_version"])
        for h in by_platform["facebook"]:
            if h["platform_id"] in stats:
                rows.append({"ts": now, "platform": "facebook", "platform_id": h["platform_id"],
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
