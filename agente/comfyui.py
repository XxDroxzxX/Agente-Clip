"""Video IA local con ComfyUI (p. ej. Wan 2.2 TI2V-5B en la GPU del propio PC).

Misma interfaz que FalVideo: generate(prompt, start_frame, dest, log). Sin start_frame es
texto→video; con él, imagen→video desde el último fotograma de la toma anterior.

El workflow es un JSON en formato API de ComfyUI («Export (API)») con marcadores que se
reemplazan en cada toma: {{prompt}}, {{seed}}, {{width}}, {{height}}, {{frames}}, {{fps}},
{{steps}} y {{start_image}}. Un marcador que ocupa todo el valor conserva el tipo (número);
dentro de un texto se reemplaza como texto. Sin imagen inicial, el nodo con {{start_image}}
se elimina junto con las conexiones que salen de él (debe alimentar una entrada opcional).
"""
from __future__ import annotations

import copy
import json
import random
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

import requests

from .paths import DATA_DIR, ROOT

WORKFLOWS_DIR = ROOT / "agente" / "workflows"
DEFAULT_WORKFLOW = "wan22_ti2v_5b.json"

# 832x480 cabe en 6-8 GB de VRAM con Wan 2.2 5B cuantizado; múltiplos de 32 (lo exige el VAE de Wan 2.2)
RESOLUTIONS = {"480p": (832, 480), "544p": (960, 544), "704p": (1280, 704)}
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".gif", ".webp")
_PH = re.compile(r"\{\{(\w+)\}\}")


def workflow_path(name: str) -> Path:
    p = Path(name or DEFAULT_WORKFLOW)
    return p if p.is_absolute() else WORKFLOWS_DIR / p


def frames_for(seconds: float, fps: int) -> int:
    """Wan necesita 4n+1 fotogramas."""
    n = max(1, round(seconds * fps / 4))
    return 4 * n + 1


def fill(node, values: dict):
    """Reemplaza los marcadores {{x}} en toda la estructura."""
    if isinstance(node, dict):
        return {k: fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [fill(v, values) for v in node]
    if isinstance(node, str):
        m = _PH.fullmatch(node)
        if m and m.group(1) in values:
            return values[m.group(1)]
        return _PH.sub(lambda mm: str(values.get(mm.group(1), mm.group(0))), node)
    return node


def drop_nodes_with(wf: dict, placeholder: str) -> dict:
    """Elimina los nodos que usan el marcador y las conexiones que apuntan a ellos."""
    tag = "{{" + placeholder + "}}"
    gone = {nid for nid, n in wf.items() if tag in json.dumps(n.get("inputs", {}), ensure_ascii=False)}
    out = {}
    for nid, n in wf.items():
        if nid in gone:
            continue
        n = copy.deepcopy(n)
        n["inputs"] = {k: v for k, v in n.get("inputs", {}).items()
                       if not (isinstance(v, list) and len(v) == 2 and str(v[0]) in gone)}
        out[nid] = n
    return out


def explain_error(body: dict | str) -> str:
    """Traduce el error de validación de ComfyUI a pasos concretos."""
    if isinstance(body, str):
        return body[:300]
    err = body.get("error") or {}
    msgs = [err.get("message", ""), err.get("details", "")]
    for ne in (body.get("node_errors") or {}).values():
        for e in ne.get("errors", []):
            msgs.append(f"{ne.get('class_type', '')}: {e.get('message', '')} {e.get('details', '')}")
    text = " | ".join(m.strip() for m in msgs if m and m.strip())
    low = text.lower()
    if err.get("type") == "invalid_prompt" and "does not exist" in low:
        m = re.search(r"node (\w+) does not exist", text, re.I) or re.search(r"class_type (\w+)", text)
        node = m.group(1) if m else "?"
        hint = " Instala ComfyUI-GGUF (custom_nodes)." if "gguf" in node.lower() else " Actualiza ComfyUI o instala el nodo que falta."
        return f"ComfyUI no tiene el nodo «{node}».{hint}"
    if "value not in list" in low:
        m = re.search(r"(\w+_name): '([^']+)' not in", text)
        if m:
            folder = {"unet_name": "models/unet", "clip_name": "models/text_encoders", "vae_name": "models/vae"}.get(m.group(1), "models")
            return f"ComfyUI no encuentra el archivo «{m.group(2)}». Colócalo en {folder} de ComfyUI y reinícialo."
    return f"ComfyUI rechazó el workflow: {text[:400]}"


_PROC: subprocess.Popen | None = None  # ComfyUI abierto por este proceso (se comparte entre videos del run)


def shutdown(url: str = "http://127.0.0.1:8188") -> None:
    """Libera la GPU al terminar: cierra ComfyUI si lo abrimos nosotros o le pide descargar los modelos."""
    global _PROC
    if _PROC is not None:
        _PROC.terminate()
        try:
            _PROC.wait(20)
        except subprocess.TimeoutExpired:
            _PROC.kill()
        _PROC = None
        return
    try:
        requests.post(f"{url.rstrip('/')}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except requests.RequestException:
        pass


class ComfyVideo:
    def __init__(self, cfg: dict, portrait: bool):
        v = cfg["video"]
        self.url = (v.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")
        self.wf_file = workflow_path(v.get("comfy_workflow") or DEFAULT_WORKFLOW)
        w, h = RESOLUTIONS.get(v.get("comfy_resolution", "480p"), RESOLUTIONS["480p"])
        self.width, self.height = (h, w) if portrait else (w, h)
        self.fps = int(v.get("comfy_fps", 24))
        self.steps = int(v.get("comfy_steps", 20))
        self.segment = float(v.get("comfy_segment_seconds", 5))
        self.style = (v.get("ai_style") or "").strip()
        self.timeout = float(v.get("comfy_timeout_min", 30)) * 60
        self.path = (v.get("comfy_path") or "").strip()
        self.client_id = uuid.uuid4().hex
        if not self.wf_file.is_file():
            raise RuntimeError(f"No se encontró el workflow de ComfyUI: {self.wf_file}")
        self.template = json.loads(self.wf_file.read_text(encoding="utf-8"))

    # ── servidor ──────────────────────────────────────

    def alive(self) -> bool:
        try:
            return requests.get(f"{self.url}/system_stats", timeout=3).ok
        except requests.RequestException:
            return False

    def ensure_running(self, log: Callable[[str], None]) -> None:
        """Si ComfyUI no responde y hay carpeta configurada, lo inicia y espera a que cargue."""
        if self.alive():
            return
        exe = Path(self.path) / "python_embeded" / "python.exe" if self.path else None
        main = Path(self.path) / "ComfyUI" / "main.py" if self.path else None
        if not exe or not exe.is_file() or not main.is_file():
            raise RuntimeError(f"ComfyUI no responde en {self.url}. Ábrelo (run_nvidia_gpu.bat) o indica su carpeta "
                               "en Configuración → Material visual para que se inicie solo.")
        port = re.search(r":(\d+)", self.url.split("//", 1)[-1])
        log("Iniciando ComfyUI (la primera vez tarda 1-2 minutos)…")
        global _PROC
        logf = open(DATA_DIR / "comfyui.log", "ab")
        _PROC = subprocess.Popen(
            [str(exe), "-s", str(main), "--windows-standalone-build", "--disable-auto-launch",
             "--listen", "127.0.0.1", "--port", port.group(1) if port else "8188"],
            cwd=self.path, stdout=logf, stderr=subprocess.STDOUT, creationflags=0x08000000)
        t0 = time.time()
        while time.time() - t0 < 240:
            if _PROC.poll() is not None:
                raise RuntimeError("ComfyUI se cerró al iniciar; revisa data/comfyui.log.")
            if self.alive():
                return
            time.sleep(3)
        raise RuntimeError("ComfyUI no terminó de iniciar en 4 minutos; revisa data/comfyui.log.")

    def release(self) -> None:
        shutdown(self.url)

    def interrupt(self) -> None:
        try:
            requests.post(f"{self.url}/interrupt", timeout=5)
        except requests.RequestException:
            pass

    # ── generación ────────────────────────────────────

    def build(self, prompt: str, image_name: str | None, seconds: float, seed: int | None = None,
              frames: int | None = None) -> dict:
        wf = self.template if image_name else drop_nodes_with(self.template, "start_image")
        if self.style:
            prompt = f"{prompt.rstrip('. ')}. {self.style}"
        return fill(wf, {
            "prompt": prompt, "seed": seed if seed is not None else random.randint(1, 2**48),
            "width": self.width, "height": self.height, "fps": self.fps, "steps": self.steps,
            "frames": frames or frames_for(seconds, self.fps), "start_image": image_name or "",
        })

    def _upload(self, image: Path) -> str:
        with open(image, "rb") as f:
            r = requests.post(f"{self.url}/upload/image", files={"image": (image.name, f, "image/png" if image.suffix.lower() == ".png" else "image/jpeg")},
                              data={"overwrite": "true", "subfolder": "agente_clips"}, timeout=60)
        r.raise_for_status()
        j = r.json()
        return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]

    def _queue(self, wf: dict) -> str:
        r = requests.post(f"{self.url}/prompt", json={"prompt": wf, "client_id": self.client_id}, timeout=60)
        if r.status_code >= 400:
            try:
                raise RuntimeError(explain_error(r.json()))
            except ValueError:
                raise RuntimeError(explain_error(r.text))
        return r.json()["prompt_id"]

    def _wait(self, pid: str, log: Callable[[str], None]) -> dict:
        t0 = time.time()
        while True:
            r = requests.get(f"{self.url}/history/{pid}", timeout=30)
            h = r.json().get(pid) if r.ok else None
            if h:
                st = h.get("status") or {}
                if st.get("status_str") == "error":
                    msg = next((m[1].get("exception_message", "") for m in st.get("messages", [])
                                if m and m[0] == "execution_error"), "error desconocido")
                    if "out of memory" in msg.lower() or "allocation" in msg.lower():
                        raise RuntimeError("La GPU se quedó sin memoria. Baja la resolución IA a 480p o los segundos por segmento.")
                    raise RuntimeError(f"ComfyUI falló al generar: {msg.strip()[:300]}")
                if st.get("completed", True) and h.get("outputs"):
                    return h["outputs"]
            if time.time() - t0 > self.timeout:
                self.interrupt()
                raise RuntimeError(f"ComfyUI tardó más de {self.timeout / 60:.0f} minutos en una toma.")
            time.sleep(3)

    @staticmethod
    def find_video(outputs: dict) -> dict:
        for node in outputs.values():
            for items in node.values():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and str(it.get("filename", "")).lower().endswith(VIDEO_EXT):
                        return it
        raise RuntimeError("ComfyUI terminó pero no devolvió ningún video (¿falta un nodo SaveVideo en el workflow?).")

    def generate(self, prompt: str, start_frame: Path | None, dest: Path, log: Callable[[str], None],
                 seconds: float | None = None) -> Path:
        image = self._upload(start_frame) if start_frame is not None else None
        t0 = time.time()
        self._fetch(self.build(prompt, image, seconds or self.segment), dest, log)
        log(f"Toma IA lista en {(time.time() - t0) / 60:.1f} min.")
        return dest

    def keyframe(self, prompt: str, dest: Path, log: Callable[[str], None]) -> Path:
        """Imagen clave (un solo cuadro, ~1 min): se revisa antes de gastar minutos de GPU en animarla."""
        from . import ffmpeg
        clip = dest.with_suffix(".mp4")
        self._fetch(self.build(prompt, None, 0, frames=1), clip, log)
        ffmpeg.run(["-i", clip, "-frames:v", "1", dest])
        clip.unlink(missing_ok=True)
        return dest

    def _fetch(self, wf: dict, dest: Path, log: Callable[[str], None]) -> None:
        out = self.find_video(self._wait(self._queue(wf), log))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with requests.get(f"{self.url}/view", params={"filename": out["filename"], "subfolder": out.get("subfolder", ""),
                                                      "type": out.get("type", "output")}, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        tmp.replace(dest)


def check(url: str) -> tuple[bool, str]:
    """Estado para la interfaz: ¿responde y tiene GPU?"""
    try:
        r = requests.get(f"{url.rstrip('/')}/system_stats", timeout=3)
        r.raise_for_status()
        dev = (r.json().get("devices") or [{}])[0]
        vram = dev.get("vram_total", 0) / 2**30
        return True, f"{dev.get('name', 'GPU')} ({vram:.0f} GB)" if vram else "En ejecución"
    except Exception:
        return False, "No responde"
