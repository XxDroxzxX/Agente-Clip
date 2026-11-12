"""Registro de eventos de un run.

Cada run vive en runs/<id>/ con:
  - run.json      estado resumido (pasos, artefactos, publicaciones)
  - events.jsonl  flujo de eventos (la interfaz lo sigue en tiempo real)
  - console.log   salida cruda
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .paths import RUNS_DIR
from .util import read_json, write_json

STEPS = [
    ("research", "Investigación de tendencias"),
    ("script", "Guion con IA"),
    ("voice", "Narración"),
    ("visuals", "Material visual"),
    ("render", "Montaje"),
    ("publish", "Publicación"),
    ("metrics", "Métricas y aprendizaje"),
]


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class Run:
    def __init__(self, run_id: str, create: bool = True, options: dict | None = None):
        self.id = run_id
        self.dir = RUNS_DIR / run_id
        self.events_path = self.dir / "events.jsonl"
        self.state_path = self.dir / "run.json"
        self._lock = threading.Lock()
        self._last_progress_emit: dict[str, float] = {}
        if create and not self.state_path.exists():
            self.dir.mkdir(parents=True, exist_ok=True)
            self.state = {
                "id": run_id,
                "status": "running",
                "pid": os.getpid(),
                "started": time.time(),
                "finished": None,
                "options": options or {},
                "title": None,
                "steps": {sid: {"label": label, "status": "pending", "progress": 0.0,
                                "message": "", "started": None, "finished": None}
                          for sid, label in STEPS},
                "items": {},
                "uploads": [],
                "error": None,
            }
            self._save()
        else:
            self.state = read_json(self.state_path, {})
            self.state["pid"] = os.getpid()
            self.state["status"] = "running"
            self.state["error"] = None
            self._save()

    # ── persistencia ───────────────────────────────────
    def _save(self):
        write_json(self.state_path, self.state)

    def _emit(self, ev: dict):
        ev = {"ts": time.time(), **ev}
        line = json.dumps(ev, ensure_ascii=False)
        with self._lock:
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def path(self, *parts) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.dir.resolve()).as_posix()

    # ── logs ───────────────────────────────────────────
    def log(self, msg: str, level: str = "info", step: str | None = None):
        print(f"[{level.upper()}] {msg}", flush=True)
        self._emit({"type": "log", "level": level, "msg": msg, "step": step})

    def info(self, msg, step=None):
        self.log(msg, "info", step)

    def warn(self, msg, step=None):
        self.log(msg, "warn", step)

    def error(self, msg, step=None):
        self.log(msg, "error", step)

    # ── pasos ──────────────────────────────────────────
    def step_start(self, sid: str, message: str = ""):
        s = self.state["steps"][sid]
        s.update(status="running", progress=0.0, message=message, started=time.time(), finished=None)
        self._save()
        self._emit({"type": "step", "step": sid, **s})

    def step_progress(self, sid: str, progress: float, message: str | None = None, force: bool = False):
        s = self.state["steps"][sid]
        s["progress"] = max(0.0, min(1.0, progress))
        if message is not None:
            s["message"] = message
        now = time.time()
        if not force and now - self._last_progress_emit.get(sid, 0) < 0.4 and progress < 1:
            return
        self._last_progress_emit[sid] = now
        self._save()
        self._emit({"type": "step", "step": sid, **s})

    def step_end(self, sid: str, status: str = "done", message: str | None = None):
        s = self.state["steps"][sid]
        s.update(status=status, finished=time.time())
        if status == "done":
            s["progress"] = 1.0
        if message is not None:
            s["message"] = message
        self._save()
        self._emit({"type": "step", "step": sid, **s})

    # ── artefactos ─────────────────────────────────────
    def artifact(self, kind: str, item: str | None = None, path: Path | None = None, **data):
        ev = {"type": "artifact", "kind": kind, "item": item, **data}
        if path is not None:
            ev["path"] = self.rel(path)
        if item:
            it = self.state["items"].setdefault(item, {})
            if kind in ("video", "thumb"):
                it[kind] = ev.get("path")
            if kind == "shot":
                it.setdefault("shots", []).append(ev.get("path"))
        self._save()
        self._emit(ev)

    def set_item(self, item: str, **data):
        self.state["items"].setdefault(item, {}).update(data)
        self._save()

    def set(self, **data):
        self.state.update(data)
        self._save()

    def add_upload(self, rec: dict):
        self.state["uploads"].append(rec)
        self._save()
        self._emit({"type": "upload", **rec})

    def finish(self, status: str, error: str | None = None):
        self.state.update(status=status, finished=time.time(), error=error)
        for s in self.state["steps"].values():
            if s["status"] == "running":
                s["status"] = "failed" if status == "failed" else "cancelled"
        self._save()
        self._emit({"type": "status", "status": status, "error": error})


