"""Miniatura personalizada para el video largo de YouTube.

1. Toma un cuadro de varias tomas (sin subtítulos ni animaciones).
2. Si hay IA con visión, elige el más llamativo; si no, el primero.
3. Remotion compone la miniatura: foto + texto gigante con una palabra resaltada.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable

from . import ffmpeg, motion


def _text(plan) -> tuple[str, str]:
    text = (getattr(plan, "thumbnail_text", "") or "").strip()
    if not text:
        anim = next((sc.animation for sc in plan.scenes if getattr(sc, "animation", None) and sc.animation.headline), None)
        text = anim.headline if anim else " ".join(plan.title.split()[:5])
    words = [w for w in text.split() if len(w.strip("¿?¡!.,")) > 0]
    highlight = max(words, key=lambda w: len(w.strip("¿?¡!.,"))) if words else ""
    return " ".join(words[:6]), highlight


def make(cfg: dict, item_dir: Path, plan, shot_files: list[Path], anim_scenes: set[int] | None,
         log: Callable[[str, str], None]) -> Path | None:
    ok, msg = motion.status()
    if not ok:
        log(f"Miniatura omitida: {msg}", "warn")
        return None
    cand_dir = item_dir / "thumb_cands"
    cand_dir.mkdir(exist_ok=True)
    # tomas sin capa animada, repartidas a lo largo del video
    pool = [f for i, f in enumerate(shot_files) if not anim_scenes or i not in anim_scenes]
    pool = pool or list(shot_files)
    step = max(1, len(pool) // 8)
    cands = []
    for k, f in enumerate(pool[::step][:8]):
        try:
            cands.append(ffmpeg.extract_frame(f, cand_dir / f"c{k}.jpg", at=0.8, width=1280))
        except Exception:
            continue
    if not cands:
        return None
    choice = cands[0]
    try:
        from . import vision
        if vision.provider(cfg) and len(cands) > 1:
            order = vision.rank_scenes(cfg, [{
                "scene": 0, "query": "youtube thumbnail",
                "narration": f"Fondo para la MINIATURA del video «{plan.title}»: el cuadro más llamativo, nítido, "
                             "colorido y representativo del tema, con espacio a la izquierda para texto.",
                "thumbs": cands}], False, log)
            if order.get(0):
                choice = cands[order[0][0]]
    except Exception as e:
        log(f"Miniatura: selección con IA no disponible ({e}).", "info")
    headline, highlight = _text(plan)
    out = item_dir / "thumbnail.jpg"
    props = {"width": 1280, "height": 720, "headline": headline, "highlight": highlight,
             "accent": cfg["video"].get("anim_color") or "#FFD633", "badge": "",
             "bg": "data:image/jpeg;base64," + base64.b64encode(choice.read_bytes()).decode()}
    done = motion.render([{"out": out, "props": props, "composition": "Miniatura", "still": True}],
                         item_dir / "thumb_job.json", log, lambda p: None)
    for f in cand_dir.glob("*"):
        f.unlink(missing_ok=True)
    cand_dir.rmdir()
    return out if 0 in done and out.is_file() else None
