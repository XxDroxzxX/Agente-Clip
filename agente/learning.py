"""Historial de publicaciones y aprendizaje.

El aprendizaje es un "bandido" epsilon-greedy sobre ESTILOS DE GANCHO:
cada video publicado registra qué estilo usó; cuando sus métricas maduran
(>= min_age_hours) se calcula una recompensa y el estilo con mejor promedio
se elige más a menudo en los siguientes guiones, sin dejar de explorar.
"""
from __future__ import annotations

import json
import math
import random
import time
from collections import defaultdict

from .paths import HISTORY_FILE, LEARNING_FILE, METRICS_FILE
from .util import read_json, write_json

HOOK_STYLES = {
    "pregunta": "Abre con una pregunta intrigante que el espectador quiera responder.",
    "dato_sorprendente": "Abre con un dato o cifra sorprendente y verificable.",
    "error_comun": "Abre señalando un error común que comete casi todo el mundo.",
    "historia": "Abre con una mini-historia o situación cotidiana con tensión.",
    "promesa": "Abre prometiendo un resultado concreto y rápido que se cumple en el video.",
    "contraintuitivo": "Abre con una afirmación contraintuitiva que rompe una creencia.",
}


# ── historial ─────────────────────────────────────────

def load_history() -> list[dict]:
    return read_json(HISTORY_FILE, []) or []


def add_history(entries: list[dict]) -> None:
    hist = load_history()
    hist.extend(entries)
    write_json(HISTORY_FILE, hist)


def load_snapshots() -> list[dict]:
    if not METRICS_FILE.is_file():
        return []
    out = []
    for line in METRICS_FILE.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def append_snapshots(rows: list[dict]) -> None:
    with open(METRICS_FILE, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── aprendizaje ───────────────────────────────────────

def reward(views: int, likes: int, comments: int, shares: int = 0, saves: int = 0) -> float:
    """Vistas en escala logarítmica por la interacción. Compartir y guardar (TikTok) valen el doble que un «me gusta»:
    son señales más fuertes de interés."""
    eng = (likes + comments + 2 * (shares + saves)) / views if views else 0.0
    return math.log1p(views) * (1 + 5 * eng)


def _r(s: dict) -> float:
    return reward(s["views"], s["likes"], s["comments"], s.get("shares", 0), s.get("saves", 0))


def recompute(min_age_hours: float) -> dict:
    """Recalcula estadísticas por estilo con la última métrica madura de cada publicación."""
    hist = {(h["platform"], h["platform_id"]): h for h in load_history() if h.get("platform_id")}
    latest: dict[tuple, dict] = {}
    for s in load_snapshots():
        key = (s["platform"], s["platform_id"])
        if key in hist and s.get("age_hours", 0) >= min_age_hours and s.get("views") is not None:
            if key not in latest or s["ts"] > latest[key]["ts"]:
                latest[key] = s

    # normaliza por plataforma Y formato: un video largo solo se compara con largos de la misma red (antes los largos
    # de YouTube, que casi no reciben impresiones en un canal nuevo, enseñaban «los videos largos rinden peor»)
    by_group = defaultdict(list)
    for key, s in latest.items():
        by_group[(key[0], fmt(hist[key]))].append(_r(s))
    stats_p = {g: (sum(v) / len(v), (max(v) - min(v)) or 1.0) for g, v in by_group.items()}

    def score(key, s) -> float:
        mean, rng = stats_p[(key[0], fmt(hist[key]))]
        return (_r(s) - mean) / rng

    styles = defaultdict(lambda: {"n": 0, "sum": 0.0})
    for key, s in latest.items():
        style = hist[key].get("hook_style")
        if not style:
            continue
        r = score(key, s)
        styles[style]["n"] += 1
        styles[style]["sum"] += r

    # además del gancho, se mide qué rasgos del video rinden mejor (música, duración, animaciones, voz)
    dims: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"n": 0, "sum": 0.0}))
    for key, s in latest.items():
        h = hist[key]
        r = score(key, s)
        for dim, val in _traits(h).items():
            if val is not None:
                dims[dim][val]["n"] += 1
                dims[dim][val]["sum"] += r

    result = {
        "updated": time.time(),
        "samples": len(latest),
        "styles": {k: {"n": v["n"], "mean": round(v["sum"] / v["n"], 4)} for k, v in styles.items()},
        "traits": {d: {k: {"n": v["n"], "mean": round(v["sum"] / v["n"], 4)} for k, v in vals.items()}
                   for d, vals in dims.items()},
    }
    write_json(LEARNING_FILE, result)
    return result


def fmt(h: dict) -> str:
    """«long» o «short» (los registros viejos no guardaban el formato: se deduce del nombre del video)."""
    return h.get("format") or ("long" if h.get("item") == "long" else "short")


def _traits(h: dict) -> dict:
    dur = h.get("duration")
    bucket = None
    if dur:
        if h.get("format") == "long" or dur > 90:
            bucket = "largo <4 min" if dur < 240 else "largo 4-8 min" if dur < 480 else "largo >8 min"
        else:
            bucket = "short <35 s" if dur < 35 else "short 35-50 s" if dur < 50 else "short >50 s"
    anims = h.get("animations")
    return {
        "music_mood": h.get("music_mood"),
        # la duración se compara solo dentro del mismo formato (un Short contra Shorts, un largo contra largos)
        f"duration_{fmt(h)}": bucket,
        "animations": None if anims is None else ("sin animaciones" if anims == 0 else
                                                  "pocas (1-2)" if anims <= 2 else "varias (3+)"),
        "voice_engine": h.get("voice_engine"),
    }


TRAIT_LABELS = {"music_mood": "música", "duration_short": "duración de los Shorts",
                "duration_long": "duración del video largo", "animations": "animaciones", "voice_engine": "voz"}


def insights(min_n: int = 2) -> list[str]:
    """Frases para el guionista: qué rasgos han rendido mejor con suficientes datos."""
    out = []
    for dim, vals in (load_learning().get("traits") or {}).items():
        good = {k: v for k, v in vals.items() if v["n"] >= min_n}
        if len(good) < 2:
            continue
        best = max(good.items(), key=lambda kv: kv[1]["mean"])
        worst = min(good.items(), key=lambda kv: kv[1]["mean"])
        if best[1]["mean"] - worst[1]["mean"] > 0.1:
            out.append(f"{TRAIT_LABELS.get(dim, dim)}: rinde mejor «{best[0]}» que «{worst[0]}»")
    return out


def load_learning() -> dict:
    return read_json(LEARNING_FILE, {"styles": {}, "samples": 0}) or {"styles": {}, "samples": 0}


def choose_hook_style(exploration: float) -> tuple[str, str]:
    """Devuelve (estilo, motivo)."""
    stats = load_learning().get("styles", {})
    untried = [s for s in HOOK_STYLES if stats.get(s, {}).get("n", 0) < 2]
    if untried:
        s = random.choice(untried)
        return s, "explorando (pocos datos de este estilo)"
    if random.random() < exploration:
        return random.choice(list(HOOK_STYLES)), "exploración aleatoria"
    best = max(HOOK_STYLES, key=lambda s: stats.get(s, {}).get("mean", -1e9))
    return best, f"mejor rendimiento histórico ({stats[best]['mean']:+.2f})"


def choose_hook_styles(keys: list[str], exploration: float) -> dict[str, tuple[str, str]]:
    """Un gancho DISTINTO por video del run ({"long": (estilo, motivo), "short_1": …}). Antes todo el run usaba el
    mismo y el aprendizaje no distinguía el gancho del tema o del día; así compiten el mismo día, con el mismo tema,
    y se aprende varias veces más rápido."""
    stats = load_learning().get("styles", {})
    out: dict[str, tuple[str, str]] = {}
    for key in keys:
        free = [s for s in HOOK_STYLES if s not in {v[0] for v in out.values()}] or list(HOOK_STYLES)
        untried = [s for s in free if stats.get(s, {}).get("n", 0) < 2]
        if untried:
            out[key] = (random.choice(untried), "explorando (pocos datos de este estilo)")
        elif random.random() < exploration:
            out[key] = (random.choice(free), "exploración aleatoria")
        else:
            best = max(free, key=lambda s: stats.get(s, {}).get("mean", -1e9))
            out[key] = (best, f"mejor rendimiento histórico ({stats[best]['mean']:+.2f})")
    return out


def top_own_titles(n: int = 5) -> list[str]:
    hist = {(h["platform"], h["platform_id"]): h for h in load_history() if h.get("platform_id")}
    best: dict[str, float] = {}
    for s in load_snapshots():
        key = (s["platform"], s["platform_id"])
        if key in hist:
            t = hist[key].get("title", "")
            best[t] = max(best.get(t, 0), _r(s))
    return [t for t, _ in sorted(best.items(), key=lambda x: -x[1])[:n]]
