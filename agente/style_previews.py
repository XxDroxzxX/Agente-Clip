"""Imágenes de muestra de cada estilo visual (para elegirlo viendo el resultado, no leyendo su nombre).

Se generan una sola vez con el modelo local (Qwen-Image en ComfyUI) y se guardan en app/static/styles/, así que
viajan con la app y funcionan también en un PC sin GPU. Todas muestran la MISMA escena: solo cambia el estilo.

    python -m agente.style_previews          # genera las que falten
    python -m agente.style_previews --force  # las regenera todas
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

from .catalog import VISUAL_STYLES

STYLE_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "styles"
SCENE = ("A young woman holding an old lantern walks down a narrow cobblestone street of an old town at dusk, "
         "looking back over her shoulder, warm windows glowing behind her, full body, vertical frame")
REALISTIC = "realistic photo, natural light"  # para «Ninguno»: el resultado sin estilo agregado


def slug(label: str) -> str:
    """«Cámara de seguridad / metraje encontrado» → «camara-de-seguridad-metraje-encontrado»."""
    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40]


def preview_name(label: str) -> str:
    return f"{slug(label)}.jpg"


def available() -> dict[str, str]:
    """{valor del estilo: nombre del archivo} de las muestras que existen."""
    return {value: preview_name(label) for value, label in VISUAL_STYLES
            if (STYLE_DIR / preview_name(label)).is_file()}


def generate(force: bool = False, log=print) -> int:
    from . import comfyui, ffmpeg
    from . import settings as S
    cfg = S.load()
    if not comfyui.edit_ready(cfg["video"].get("comfy_path", "")):
        raise SystemExit("Faltan los modelos de Qwen-Image-Edit en ComfyUI (ver DOCUMENTACION_PROYECTO.md).")
    todo = [(v, l) for v, l in VISUAL_STYLES if force or not (STYLE_DIR / preview_name(l)).is_file()]
    if not todo:
        log("Todas las muestras ya existen.")
        return 0
    STYLE_DIR.mkdir(parents=True, exist_ok=True)
    ai = comfyui.ComfyVideo(cfg, portrait=True)
    ai.ensure_running(log)
    done = 0
    try:
        for value, label in todo:
            raw = STYLE_DIR / f"{slug(label)}.png"
            log(f"Estilo «{label}»…")
            ai.edit_image(f"{SCENE}. {value or REALISTIC}. No text.", None, raw, log)
            # tarjeta liviana para la interfaz (360x640, ~40 KB)
            ffmpeg.run(["-i", raw, "-vf", "scale=360:-2", "-q:v", "4", STYLE_DIR / preview_name(label)])
            raw.unlink(missing_ok=True)
            done += 1
    finally:
        ai.release()
    log(f"{done} muestra(s) listas en {STYLE_DIR}.")
    return done


if __name__ == "__main__":
    generate(force="--force" in sys.argv)
