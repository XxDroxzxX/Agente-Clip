"""Limpieza automática de espacio en disco.

- Archivos de trabajo de runs viejos (tomas, fuentes, capas animadas, audios intermedios):
  se borran pasados `keep_work_days`. Se conservan el video final, miniaturas, guion y registros.
- Caché de clips de stock: si supera `cache_max_gb`, se borra lo usado hace más tiempo.
- Videos finales: solo si `delete_videos_days` > 0 (por defecto nunca).
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .paths import CACHE_DIR, LOCK_FILE, RUNS_DIR
from .util import read_json

WORK_DIRS = ("shots", "sources", "anim", "audio", "fonts", "thumb_cands")
WORK_FILES = ("narration.wav", "music.wav", "music.mp3", "sfx.wav", "audio_mix.wav", "silent.mp4", "shots.txt",
              "subs.ass", "audio.json", "shots.json", "thumb_job.json")


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


def _active_run() -> str | None:
    lock = read_json(LOCK_FILE) or {}
    return lock.get("run_id")


def usage() -> dict:
    runs = [d for d in RUNS_DIR.iterdir() if d.is_dir()] if RUNS_DIR.is_dir() else []
    work = videos = 0
    for d in runs:
        for item in d.iterdir():
            if not item.is_dir():
                continue
            for name in WORK_DIRS + WORK_FILES:
                work += _size(item / name)
            videos += _size(item / "final.mp4")
    return {"runs": len(runs), "work_gb": round(work / 1e9, 2), "videos_gb": round(videos / 1e9, 2),
            "cache_gb": round(_size(CACHE_DIR) / 1e9, 2)}


def run(cfg: dict, force: bool = False) -> dict:
    """Aplica la política de limpieza. force=True borra el trabajo de TODOS los runs terminados (no el activo)."""
    st = cfg.get("storage", {})
    keep = 0 if force else float(st.get("keep_work_days", 7))
    del_videos = float(st.get("delete_videos_days", 0))
    now = time.time()
    active = _active_run()
    freed = 0
    for d in (RUNS_DIR.iterdir() if RUNS_DIR.is_dir() else []):
        if not d.is_dir() or d.name == active:
            continue
        state = read_json(d / "run.json") or {}
        if state.get("status") in ("running", "queued"):
            continue
        age_days = (now - float(state.get("finished") or state.get("started") or d.stat().st_mtime)) / 86400
        if age_days < keep:
            continue
        for item in d.iterdir():
            if not item.is_dir():
                continue
            for name in WORK_DIRS + WORK_FILES:
                p = item / name
                if p.exists():
                    freed += _size(p)
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            if del_videos > 0 and age_days >= del_videos and (item / "final.mp4").is_file():
                freed += _size(item / "final.mp4")
                (item / "final.mp4").unlink(missing_ok=True)
    # caché: lo usado hace más tiempo se va primero
    limit = float(st.get("cache_max_gb", 5)) * 1e9
    files = [f for f in CACHE_DIR.rglob("*") if f.is_file()] if CACHE_DIR.is_dir() else []
    total = sum(f.stat().st_size for f in files)
    if total > limit or force:
        target = 0 if force else limit * 0.8
        for f in sorted(files, key=lambda f: max(f.stat().st_atime, f.stat().st_mtime)):
            if total <= target:
                break
            sz = f.stat().st_size
            f.unlink(missing_ok=True)
            total -= sz
            freed += sz
    return {"freed_gb": round(freed / 1e9, 2), **usage()}
