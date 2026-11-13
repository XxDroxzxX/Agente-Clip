"""Animaciones con Remotion (motion graphics).

Cada animación es una capa TRANSPARENTE (ProRes 4444) del tamaño del video que se
superpone a una toma en ffmpeg. Las plantillas viven en motion/src/templates y el
guion elige cuál usar en cada escena (titulo, lista, dato, frase, cta).
Requiere Node.js y `npm install` en motion/ (lo hace setup.ps1).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Callable

from .paths import ROOT

MOTION_DIR = ROOT / "motion"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TYPES = ("titulo", "lista", "dato", "frase", "cta")


def status() -> tuple[bool, str]:
    """(disponible, mensaje para el usuario)."""
    if not shutil.which("node"):
        return False, "Falta Node.js: instálalo desde nodejs.org (versión LTS) y vuelve a ejecutar la instalación."
    if not (MOTION_DIR / "node_modules" / "remotion").is_dir():
        return False, "Remotion no está instalado: vuelve a abrir AgenteDeClips.exe o ejecuta setup.ps1."
    return True, "Remotion listo"


def overlay_props(anim: dict, W: int, H: int, duration: float, fps: int, accent: str) -> dict:
    return {
        "type": anim.get("type", "titulo"),
        "width": W,
        "height": H,
        "fps": fps,
        "durationInFrames": max(1, round(duration * fps)),
        "accent": accent,
        "headline": anim.get("headline") or "",
        "highlight": anim.get("highlight") or "",
        "items": [str(x) for x in (anim.get("items") or [])][:5],
        "value": anim.get("value") or "",
        "label": anim.get("label") or "",
    }


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9%]", "", "".join(c for c in s if not unicodedata.combining(c)))


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # tolera plurales y conjugaciones cercanas: «lentejas» ~ «lenteja», «cocinan» ~ «cocina»
    return len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5]


def sync_frames(anim: dict, words: list, offset: float, fps: int) -> dict:
    """Cuadros (relativos a la toma) en que la voz dice cada parte de la animación; -1 = sin coincidencia.
    words: palabras de la escena con .text y .start (s). offset: inicio de la toma dentro de la escena."""
    spoken = [(_norm(w.text), w.start - offset) for w in words]
    lead = 3  # la animación entra un poco antes de la palabra

    def find(token: str, cursor: int) -> tuple[int, int]:
        t = _norm(token)
        if len(t) < 3 and not t.isdigit():
            return -1, cursor
        for k in range(cursor, len(spoken)):
            if _same(t, spoken[k][0]) or (t.isdigit() and re.sub(r"\D", "", spoken[k][0]) == t):
                return max(0, round(spoken[k][1] * fps) - lead), k + 1
        return -1, cursor

    out = {"wordFrames": [], "itemFrames": [], "valueFrame": -1}
    cur = 0
    for tok in (anim.get("headline") or "").split():
        f, cur = find(tok, cur)
        out["wordFrames"].append(f)
    cur = 0
    for item in anim.get("items") or []:
        toks = sorted(item.split(), key=lambda x: -len(_norm(x)))[:2]  # las palabras más distintivas
        # el elemento entra con la primera de ellas que diga la voz
        hits = [h for h in (find(tok, cur) for tok in toks) if h[0] >= 0]
        f, nxt = min(hits) if hits else (-1, cur)
        out["itemFrames"].append(f)
        cur = nxt if f >= 0 else cur
    digits = re.sub(r"\D", "", anim.get("value") or "")
    if digits:
        out["valueFrame"], _ = find(digits, 0)
    if out["valueFrame"] < 0 and anim.get("label"):
        out["valueFrame"], _ = find(max(anim["label"].split(), key=lambda x: len(_norm(x))), 0)
    return out


def render(jobs: list[dict], jobs_file: Path, log: Callable[[str, str], None],
           progress: Callable[[float], None]) -> set[int]:
    """Renderiza las capas. jobs = [{"out": Path, "props": {...}}]. Devuelve los índices logrados."""
    ok, msg = status()
    if not ok:
        log(f"Animaciones omitidas: {msg}", "warn")
        return set()
    jobs_file.write_text(json.dumps([{"out": str(j["out"]), "props": j["props"],
                                      "composition": j.get("composition", "Overlay"), "still": j.get("still", False)}
                                     for j in jobs], ensure_ascii=False), encoding="utf-8")
    proc = subprocess.Popen(["node", "render.mjs", str(jobs_file)], cwd=MOTION_DIR,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", creationflags=CREATE_NO_WINDOW)
    done: set[int] = set()
    n = max(1, len(jobs))
    for line in proc.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "progress":
            progress((ev["job"] + float(ev.get("progress", 0))) / n)
        elif t == "done":
            done.add(ev["job"])
        elif t == "log":
            log(ev["msg"], "info")
        elif t == "error":
            log(f"Animación {ev['job'] + 1}: {ev['msg']}", "warn")
        elif t == "fatal":
            log(f"Remotion falló: {ev['msg']}", "warn")
    proc.wait()
    if proc.returncode not in (0, None) and not done:
        err = (proc.stderr.read() or "").strip().splitlines()[-1:] if proc.stderr else []
        log(f"Remotion terminó con error {proc.returncode}. {' '.join(err)[:300]}", "warn")
    return done
