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

def reward(views: int, likes: int, comments: int) -> float:
    eng = (likes + comments) / views if views else 0.0
    return math.log1p(views) * (1 + 5 * eng)


def recompute(min_age_hours: float) -> dict:
    """Recalcula estadísticas por estilo con la última métrica madura de cada publicación."""
    hist = {(h["platform"], h["platform_id"]): h for h in load_history() if h.get("platform_id")}
    latest: dict[tuple, dict] = {}
    for s in load_snapshots():
        key = (s["platform"], s["platform_id"])
        if key in hist and s.get("age_hours", 0) >= min_age_hours:
            if key not in latest or s["ts"] > latest[key]["ts"]:
                latest[key] = s

    # normaliza por plataforma para que una no domine a otra
    by_platform = defaultdict(list)
    for key, s in latest.items():
        by_platform[key[0]].append(reward(s["views"], s["likes"], s["comments"]))
    stats_p = {p: (sum(v) / len(v), (max(v) - min(v)) or 1.0) for p, v in by_platform.items()}

    styles = defaultdict(lambda: {"n": 0, "sum": 0.0})
    for key, s in latest.items():
        style = hist[key].get("hook_style")
        if not style:
            continue
        mean, rng = stats_p[key[0]]
        r = (reward(s["views"], s["likes"], s["comments"]) - mean) / rng
        styles[style]["n"] += 1
        styles[style]["sum"] += r

    result = {
        "updated": time.time(),
        "samples": len(latest),
        "styles": {k: {"n": v["n"], "mean": round(v["sum"] / v["n"], 4)} for k, v in styles.items()},
    }
    write_json(LEARNING_FILE, result)
    return result


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


def top_own_titles(n: int = 5) -> list[str]:
    hist = {(h["platform"], h["platform_id"]): h for h in load_history() if h.get("platform_id")}
    best: dict[str, float] = {}
    for s in load_snapshots():
        key = (s["platform"], s["platform_id"])
        if key in hist:
            t = hist[key].get("title", "")
            best[t] = max(best.get(t, 0), reward(s["views"], s["likes"], s["comments"]))
    return [t for t, _ in sorted(best.items(), key=lambda x: -x[1])[:n]]
