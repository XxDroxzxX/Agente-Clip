"""Interfaz web local del Agente de Clips.

Ejecutar:  python -m app.server   (o run_ui.ps1)
Abre http://localhost:8585 — solo escucha en la máquina local.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agente import learning, motion  # noqa: E402
from agente import settings as S  # noqa: E402
from agente.events import STEPS, new_run_id  # noqa: E402
from agente.paths import LOCK_FILE, MUSIC_DIR, RUNS_DIR  # noqa: E402
from agente.util import pid_alive, read_json, write_json  # noqa: E402

PORT = int(os.environ.get("AGENTE_PORT", "8585"))
TOKEN = secrets.token_urlsafe(24)
STATIC = Path(__file__).parent / "static"
REDIRECT_URI = f"http://localhost:{PORT}/callback"
ALLOWED_HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
CREATE_FLAGS = (0x08000000 | 0x00000200) if os.name == "nt" else 0  # sin ventana + grupo propio
TASK_NAME = "AgenteDeClips"

app = FastAPI(title="Agente de Clips", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_procs: dict[str, subprocess.Popen] = {}
_connect_state: dict[str, dict] = {"youtube": {"state": "idle"}}
_cache: dict[str, tuple[float, object]] = {}


# ── seguridad ─────────────────────────────────────────

@app.middleware("http")
async def guard(request: Request, call_next):
    if request.headers.get("host", "") not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "Host no permitido"}, status_code=403)
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/media/"):
        tok = request.headers.get("x-token") or request.query_params.get("t")
        if not tok or not secrets.compare_digest(tok, TOKEN):
            return JSONResponse({"detail": "No autorizado"}, status_code=401)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.get("/", response_class=HTMLResponse)
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return html.replace("__TOKEN__", TOKEN)


# ── utilidades de runs ────────────────────────────────

def _run_dir(run_id: str) -> Path:
    d = (RUNS_DIR / run_id).resolve()
    if d.parent != RUNS_DIR.resolve() or not d.is_dir():
        raise HTTPException(404, "Run no encontrado")
    return d


def _active() -> dict | None:
    lock = read_json(LOCK_FILE)
    if lock and pid_alive(lock.get("pid", 0)):
        return lock
    return None


def _summary(d: Path) -> dict | None:
    st = read_json(d / "run.json")
    if not st:
        return None
    if st.get("status") == "running" and not pid_alive(st.get("pid", 0)):
        st["status"] = "interrupted"
    items = st.get("items", {})
    thumb = next((f"{k}/thumb.jpg" for k in items if (d / k / "thumb.jpg").is_file()), None)
    return {
        "id": st["id"], "status": st["status"], "title": st.get("title"), "topic": st.get("topic"),
        "started": st.get("started"), "finished": st.get("finished"), "error": st.get("error"),
        "items": {k: {"duration": v.get("duration"), "video": v.get("video"), "portrait": v.get("portrait")}
                  for k, v in items.items()},
        "uploads": [u for u in st.get("uploads", []) if u.get("platform_id")],
        "upload_errors": len([u for u in st.get("uploads", []) if not u.get("platform_id")]),
        "thumb": thumb, "options": st.get("options", {}),
    }


def _spawn(args: list[str], run_id: str):
    if _active():
        raise HTTPException(409, "Ya hay un proceso en curso.")
    d = RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    log = open(d / "console.log", "a", encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "agente.pipeline", *args], cwd=str(ROOT), stdout=log,
                            stderr=subprocess.STDOUT, env=env, creationflags=CREATE_FLAGS)
    _procs[run_id] = proc

    def watch():
        code = proc.wait()
        log.close()
        _procs.pop(run_id, None)
        st = read_json(d / "run.json")
        if st is None or st.get("status") == "running":
            tail = ""
            try:
                tail = (d / "console.log").read_text(encoding="utf-8")[-800:]
            except OSError:
                pass
            if st is None:
                st = {"id": run_id, "steps": {}, "items": {}, "uploads": [], "started": time.time()}
            st.update(status="failed", finished=time.time(),
                      error=f"El proceso terminó inesperadamente (código {code}). {tail}".strip())
            write_json(d / "run.json", st)
            with open(d / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "type": "status", "status": "failed", "error": st["error"]}) + "\n")

    threading.Thread(target=watch, daemon=True).start()
    # espera a que el pipeline cree el estado inicial
    for _ in range(40):
        if (d / "run.json").is_file():
            break
        time.sleep(0.1)


# ── estado general ────────────────────────────────────

def _ollama_up(url: str) -> bool:
    c = _cache.get("ollama_up")
    if c and time.time() - c[0] < 15:
        return c[1]
    import requests
    try:
        ok = requests.get(url.rstrip("/") + "/api/tags", timeout=0.7).ok
    except Exception:
        ok = False
    _cache["ollama_up"] = (time.time(), ok)
    return ok


def _comfy_status(v: dict) -> tuple[bool, str]:
    c = _cache.get("comfy_up")
    if c and time.time() - c[0] < 15:
        return c[1]
    from agente import comfyui
    ok, msg = comfyui.check(v.get("comfy_url") or "http://127.0.0.1:8188")
    if ok:
        msg = f"En ejecución — {msg}"
    elif (Path(v.get("comfy_path") or ".") / "python_embeded" / "python.exe").is_file():
        ok, msg = True, "Cerrado; cada run lo abrirá solo"
    else:
        msg = "No responde: ábrelo (run_nvidia_gpu.bat) o indica su carpeta en Material visual"
    _cache["comfy_up"] = (time.time(), (ok, msg))
    return ok, msg


def _readiness(cfg: dict, sec: dict) -> list[dict]:
    r = []
    if cfg["llm"]["provider"] == "claude":
        r.append({"ok": sec["anthropic_api_key"], "label": "Claude API key", "hint": "Necesaria para escribir los guiones",
                  "critical": True})
    elif cfg["llm"]["provider"] == "gemini":
        r.append({"ok": sec["gemini_api_key"], "label": "Gemini API key (gratis)", "hint": "Necesaria para escribir los guiones",
                  "critical": True})
    else:
        up = _ollama_up(cfg["llm"]["ollama_url"])
        r.append({"ok": up, "label": f"Ollama ({cfg['llm']['ollama_model']})",
                  "hint": "En ejecución" if up else "No está en ejecución: ábrelo o instálalo desde ollama.com",
                  "critical": True})
    if cfg["video"]["visual_provider"] == "fal":
        r.append({"ok": sec["fal_api_key"], "label": "fal.ai API key", "hint": "Para generar video con IA", "critical": False})
    elif cfg["video"]["visual_provider"] == "comfyui":
        ok, msg = _comfy_status(cfg["video"])
        r.append({"ok": ok, "label": "ComfyUI (video IA local)", "hint": msg, "critical": False})
    r.append({"ok": sec["pixabay_api_key"] or sec["pexels_api_key"], "label": "Clips de stock (Pixabay o Pexels)",
              "hint": "Clips reales por escena (sin clave: fondos de color)", "critical": False})
    r.append({"ok": sec["youtube_api_key"], "label": "YouTube Data API key", "hint": "Investigación de tendencias", "critical": False})
    p = cfg["publish"]
    from agente.publish import browser
    if p["youtube"]:
        by_browser = p.get("youtube_method", "browser") == "browser"
        r.append({"ok": browser.status("youtube").get("connected") if by_browser else sec["youtube_token"],
                  "label": "YouTube conectado" + (" (navegador)" if by_browser else ""),
                  "hint": "Para publicar en tu canal", "critical": False})
    if p["tiktok"]:
        by_browser = p.get("tiktok_method", "browser") == "browser"
        r.append({"ok": browser.status("tiktok").get("connected") if by_browser else sec["tiktok_token"],
                  "label": "TikTok conectado" + (" (navegador)" if by_browser else ""),
                  "hint": "Para publicar Shorts en TikTok", "critical": False})
    if p["facebook"]:
        r.append({"ok": sec["facebook_page_token"], "label": "Facebook Page token", "hint": "Para publicar en tu página", "critical": False})
    if p.get("instagram"):
        r.append({"ok": sec["facebook_page_token"], "label": "Instagram (token de página)",
                  "hint": "Reels en tu Instagram profesional vinculado a la página", "critical": False})
    uses_stock = cfg["video"]["visual_provider"] != "fal" or cfg["video"].get("ai_select", "smart") != "all"
    if uses_stock and cfg["video"].get("smart_clips", "auto") != "off":
        from agente import vision
        prov = vision.provider(cfg)
        r.append({"ok": prov is not None, "label": "Selección de clips con visión",
                  "hint": f"Con {'Gemini (gratis)' if prov == 'gemini' else 'Claude'}" if prov
                  else "Agrega la Gemini API key (gratis) para que la IA elija los clips", "critical": False})
    if cfg["video"]["music"] and cfg["video"].get("music_source") == "lyria":
        r.append({"ok": sec["gemini_api_key"], "label": "Música con Lyria", "hint": "Usa la Gemini API key (con facturación activa); si falla, se genera",
                  "critical": False})
    return r


@app.get("/api/state")
def state():
    cfg = S.load()
    sec = S.secrets_status()
    active = _active()
    legacy = (ROOT / "config.yaml").is_file() or (ROOT / "client_secret.json").is_file()
    return {"active": active, "steps": [{"id": i, "label": l} for i, l in STEPS], "readiness": _readiness(cfg, sec),
            "auto_publish": cfg["publish"]["auto_publish"], "niche": cfg["content"]["niche"], "legacy_files": legacy}


# ── runs ──────────────────────────────────────────────

@app.get("/api/runs")
def list_runs(limit: int = 50):
    out = []
    for d in sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)[:limit]:
        s = _summary(d)
        if s:
            out.append(s)
    return out


@app.post("/api/runs")
def start_run(body: dict = Body(default={})):
    run_id = new_run_id()
    flag = "--publish" if body.get("publish") else "--no-publish"
    _spawn(["--run-id", run_id, flag], run_id)
    return {"id": run_id}


@app.post("/api/metrics")
def run_metrics():
    run_id = new_run_id()
    _spawn(["--run-id", run_id, "--metrics-only"], run_id)
    return {"id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    d = _run_dir(run_id)
    st = read_json(d / "run.json", {})
    if st.get("status") == "running" and not pid_alive(st.get("pid", 0)):
        st["status"] = "interrupted"
    script = read_json(d / "script.json")
    research = read_json(d / "research.json")
    return {"run": st, "script": script, "research_top": (research or {}).get("videos", [])[:5]}


@app.post("/api/runs/{run_id}/publish")
def publish_run(run_id: str):
    d = _run_dir(run_id)
    if not any((d / k / "final.mp4").is_file() for k in read_json(d / "run.json", {}).get("items", {})):
        raise HTTPException(400, "Este run no tiene videos terminados.")
    _spawn(["--publish-only", run_id], run_id)
    return {"id": run_id}


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str):
    d = _run_dir(run_id)
    st = read_json(d / "run.json", {})
    if st.get("status") not in ("failed", "cancelled", "interrupted"):
        raise HTTPException(400, "Solo se pueden reintentar runs fallidos o cancelados.")
    if st.get("options", {}).get("mode") == "metrics":
        raise HTTPException(400, "Para métricas, inicia una actualización nueva.")
    _spawn(["--resume", run_id], run_id)
    return {"id": run_id}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    d = _run_dir(run_id)
    st = read_json(d / "run.json", {})
    pid = st.get("pid")
    if pid and pid_alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=0x08000000)
        v = S.load()["video"]
        if v["visual_provider"] == "comfyui":  # un ComfyUI abierto aparte seguiría generando la toma en curso
            import requests
            try:
                requests.post(v["comfy_url"].rstrip("/") + "/interrupt", timeout=2)
            except Exception:
                pass
    time.sleep(0.5)
    st = read_json(d / "run.json", {})
    if st.get("status") == "running":
        for s in st.get("steps", {}).values():
            if s.get("status") in ("running", "pending"):
                s["status"] = "cancelled"
        st.update(status="cancelled", finished=time.time(), error="Cancelado por el usuario")
        write_json(d / "run.json", st)
        with open(d / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "type": "status", "status": "cancelled"}) + "\n")
    lock = read_json(LOCK_FILE)
    if lock and lock.get("run_id") == run_id:
        LOCK_FILE.unlink(missing_ok=True)
    return {"ok": True}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    d = _run_dir(run_id)
    act = _active()
    if act and act.get("run_id") == run_id:
        raise HTTPException(409, "No se puede borrar un run en curso.")
    shutil.rmtree(d)
    return {"ok": True}


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str, request: Request, offset: int = 0):
    d = _run_dir(run_id)
    path = d / "events.jsonl"

    async def gen():
        pos = offset
        last_ping = time.time()
        buf = b""
        while True:
            if await request.is_disconnected():
                return
            chunk = b""
            if path.is_file():
                with open(path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
            if chunk:
                start = pos - len(buf)          # offset absoluto del inicio de buf
                buf += chunk
                pos += len(chunk)
                *lines, buf = buf.split(b"\n")
                cursor = start
                for line in lines:
                    cursor += len(line) + 1     # offset justo después de esta línea
                    if line.strip():
                        yield f"id: {cursor}\ndata: {line.decode('utf-8', 'replace')}\n\n"
                last_ping = time.time()
            else:
                st = read_json(d / "run.json", {})
                running = st.get("status") == "running" and pid_alive(st.get("pid", 0))
                if not running and run_id not in _procs:
                    yield f"event: end\ndata: {json.dumps({'status': st.get('status')})}\n\n"
                    return
                if time.time() - last_ping > 15:
                    yield ": ping\n\n"
                    last_ping = time.time()
                await asyncio.sleep(0.35)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/media/{run_id}/{rel:path}")
def media(run_id: str, rel: str):
    d = _run_dir(run_id)
    p = (d / rel).resolve()
    if not p.is_relative_to(d) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


# ── configuración ─────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    return {"settings": S.load(), "secrets": S.secrets_status(),
            "secret_meta": {k: {"label": v[0], "help": v[1]} for k, v in S.SECRETS.items()},
            "redirect_uri": REDIRECT_URI, "music_dir": str(MUSIC_DIR),
            "music_files": sorted(p.name for p in MUSIC_DIR.glob("*") if p.is_file()),
            "motion": dict(zip(("ok", "msg"), motion.status())),
            "gemini_voices": __import__("agente.tts", fromlist=["GEMINI_VOICES"]).GEMINI_VOICES,
            "catalog": __import__("agente.catalog", fromlist=["for_ui"]).for_ui(),
            "workflows": sorted(p.name for p in (ROOT / "agente" / "workflows").glob("*.json"))}


@app.get("/api/ollama-models")
def ollama_models():
    """Modelos ya instalados en Ollama (para elegirlos de una lista); vacío si Ollama no responde."""
    import requests
    try:
        url = S.load()["llm"]["ollama_url"].rstrip("/")
        tags = requests.get(f"{url}/api/tags", timeout=2).json().get("models", [])
        return sorted(m["name"] for m in tags if m.get("name"))
    except Exception:
        return []


@app.get("/api/storage")
def storage_usage():
    from agente import cleanup
    return cleanup.usage()


@app.post("/api/storage/cleanup")
def storage_cleanup():
    from agente import cleanup
    return cleanup.run(S.load(), force=True)


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    _cache.pop("ollama_up", None)
    _cache.pop("comfy_up", None)
    _cache.pop("fb_page", None)
    saved, fixes = S.save(body)
    return {"settings": saved, "fixes": fixes}


@app.put("/api/secrets/{name}")
def put_secret(name: str, body: dict = Body(...)):
    if name not in S.SECRETS:
        raise HTTPException(404, "Credencial desconocida")
    value = (body.get("value") or "").strip()
    if not value:
        raise HTTPException(400, "El valor está vacío")
    if name == "youtube_client_secret":
        try:
            j = json.loads(value)
            if not ("installed" in j or "web" in j):
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Pega el contenido completo de client_secret.json (con la clave «installed»).")
    note = ""
    if name == "facebook_page_token":
        from agente.publish import facebook
        try:
            value, note = facebook.normalize_token(value, S.load()["publish"]["facebook_graph_version"])
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    S.set_secret(name, value)
    _cache.pop("fb_page", None)
    _cache.pop("ig_acc", None)
    return {"ok": True, "note": note}


@app.delete("/api/secrets/{name}")
def del_secret(name: str):
    if name not in S.SECRETS and name not in S.OAUTH_TOKENS:
        raise HTTPException(404)
    S.delete_secret(name)
    _cache.pop("fb_page", None)
    return {"ok": True}


def _friendly_error(service: str, e: Exception) -> str:
    """Traduce excepciones de red y de APIs a un mensaje que el usuario pueda resolver."""
    import requests
    name = type(e).__name__
    text = str(e).lower()
    if isinstance(e, requests.Timeout) or name in ("APITimeoutError", "TimeoutError"):
        return f"{service} tardó demasiado en responder. Intenta de nuevo."
    if isinstance(e, requests.ConnectionError) or name in ("APIConnectionError", "ServerNotFoundError"):
        return f"No se pudo conectar con {service}. Revisa tu conexión a internet."
    status = getattr(e, "status_code", None)                       # anthropic
    if status is None:
        status = getattr(getattr(e, "resp", None), "status", None)  # googleapiclient
    if status is None and getattr(e, "response", None) is not None:
        status = getattr(e.response, "status_code", None)            # requests
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status == 401 or "api key not valid" in text or "invalid x-api-key" in text or "access token" in text:
        return "La clave no es válida o expiró. Revisa que la copiaste completa y sin espacios."
    if status == 403:
        if "has not been used" in text or "is disabled" in text:
            return f"La API de {service} no está habilitada en tu proyecto. Actívala en la consola del proveedor."
        return "La clave no tiene permiso para este servicio. Revisa sus restricciones o permisos."
    if status == 429:
        return "Se alcanzó el límite de solicitudes. Espera unos minutos y vuelve a probar."
    if status is not None and status >= 500:
        return f"{service} no está disponible en este momento (error {status}). Intenta más tarde."
    if status is not None:
        return f"{service} rechazó la solicitud (error {status})."
    return f"Error inesperado: {str(e)[:200]}"


_TEST_LABELS = {"gemini_media": "Gemini (imagen y video)", "gemini": "Gemini", "anthropic": "Claude", "pexels": "Pexels", "pixabay": "Pixabay", "youtube_api": "YouTube",
                "facebook": "Facebook", "instagram": "Instagram", "ollama": "Ollama"}


@app.post("/api/test/{service}")
def test_service(service: str):
    import requests
    if service not in _TEST_LABELS:
        raise HTTPException(404)
    label = _TEST_LABELS[service]
    no_key = {"ok": False, "msg": "No hay clave guardada"}
    try:
        if service == "anthropic":
            import anthropic
            key = S.get_secret("anthropic_api_key")
            if not key:
                return no_key
            model = S.load()["llm"]["claude_model"]
            try:
                anthropic.Anthropic(api_key=key).models.retrieve(model)
            except anthropic.NotFoundError:
                return {"ok": False, "msg": f"La clave es válida, pero el modelo «{model}» no está disponible para tu cuenta."}
            return {"ok": True, "msg": "Clave válida y modelo disponible"}
        if service == "gemini_media":
            from agente import gemini_media
            if not S.get_secret("gemini_media_api_key"):
                return no_key
            try:
                m = gemini_media.list_models()
            except gemini_media.MediaError as e:
                return {"ok": False, "msg": str(e)}
            img = ", ".join(m["image"][:3]) or "ninguno"
            vid = ", ".join(m["video"][:3]) or "ninguno"
            return {"ok": bool(m["image"] or m["video"]),
                    "msg": f"Clave válida. Imagen (Nano Banana): {img}. Video (Veo): {vid}. "
                           "Ver los modelos no garantiza cuota: la primera generación lo confirma."}
        if service == "gemini":
            from agente import gemini
            if not S.get_secret("gemini_api_key"):
                return no_key
            try:
                models = gemini.list_models()
            except gemini.GeminiError as e:
                return {"ok": False, "msg": str(e)}
            want = S.load()["llm"].get("gemini_model") or gemini.FREE_MODELS[0]
            free = [m for m in gemini.FREE_MODELS if m in models]
            if want in models:
                return {"ok": True, "msg": f"Clave válida. Modelo {want} disponible (más {len(free) - 1} de respaldo gratis)."}
            return {"ok": bool(free), "msg": f"Clave válida, pero «{want}» no aparece en tu cuenta. "
                    + (f"Disponibles gratis: {', '.join(free)}." if free else "No se encontraron modelos gratuitos.")}
        if service in ("pexels", "pixabay"):
            from agente.visuals import check_status
            key = S.get_secret(f"{service}_api_key")
            if not key:
                return no_key
            if service == "pexels":
                r = requests.get("https://api.pexels.com/videos/search", params={"query": "nature", "per_page": 1},
                                 headers={"Authorization": key}, timeout=20)
            else:
                r = requests.get("https://pixabay.com/api/videos/", params={"key": key, "q": "nature", "per_page": 3},
                                 timeout=20)
            try:
                check_status(label, r, "")
            except RuntimeError as e:
                return {"ok": False, "msg": str(e)}
            return {"ok": True, "msg": "Clave válida"}
        if service == "youtube_api":
            from googleapiclient.discovery import build
            key = S.get_secret("youtube_api_key")
            if not key:
                return no_key
            build("youtube", "v3", developerKey=key, cache_discovery=False).videos().list(
                part="id", chart="mostPopular", maxResults=1).execute()
            return {"ok": True, "msg": "Clave válida"}
        if service == "facebook":
            from agente.publish import facebook
            if not S.get_secret("facebook_page_token"):
                return no_key
            info = facebook.page_info(S.load()["publish"]["facebook_graph_version"])
            return {"ok": True, "msg": f"Página: {info.get('name')}"}
        if service == "instagram":
            from agente.publish import instagram
            if not S.get_secret("facebook_page_token"):
                return {"ok": False, "msg": "Primero guarda el Facebook Page access token"}
            try:
                ig = instagram.account(S.load()["publish"]["facebook_graph_version"])
            except RuntimeError as e:
                return {"ok": False, "msg": str(e)}
            return {"ok": True, "msg": f"Instagram vinculado: @{ig.get('username', '?')}"}
        if service == "ollama":
            cfg = S.load()["llm"]
            base, model = cfg["ollama_url"].rstrip("/"), cfg["ollama_model"]
            _cache.pop("ollama_up", None)
            try:
                r = requests.get(base + "/api/tags", timeout=5)
            except requests.ConnectionError:
                return {"ok": False, "msg": f"Ollama no está en ejecución en {base}. Instálalo desde ollama.com, "
                                            f"ábrelo y luego ejecuta en una terminal: ollama pull {model}"}
            names = [m["name"] for m in r.json().get("models", [])]
            ok = any(n == model or n.startswith(model + ":") for n in names)
            return {"ok": ok, "msg": "Ollama en ejecución y modelo disponible" if ok
                    else f"Ollama está en ejecución, pero falta el modelo. Ejecuta en una terminal: ollama pull {model}"}
    except Exception as e:
        return {"ok": False, "msg": _friendly_error(label, e)}


def _cached(key: str, fn, ttl: float = 300):
    c = _cache.get(key)
    if not c or time.time() - c[0] > (ttl if not _has_error(c[1]) else 20):
        _cache[key] = (time.time(), fn())
    return _cache[key][1]


def _has_error(v) -> bool:
    return isinstance(v, tuple) and len(v) == 2 and v[1] is not None


def _fb_page() -> tuple[str | None, str | None]:
    from agente.publish import facebook
    try:
        return facebook.page_info(S.load()["publish"]["facebook_graph_version"]).get("name"), None
    except Exception as e:
        msg = str(e)
        if "expired" in msg.lower() or "session has expired" in msg.lower():
            return None, ("El token de Facebook venció. Genera un token de página que no vence "
                          "(ver «¿Cómo lo obtengo?») y guárdalo de nuevo.")
        return None, _friendly_error("Facebook", e)


def _ig_account() -> tuple[str | None, str | None]:
    from agente.publish import instagram
    try:
        ig = instagram.account(S.load()["publish"]["facebook_graph_version"])
        return "@" + ig.get("username", "?"), None
    except Exception as e:
        if "instagram_business_account" in str(e) and "nonexisting field" in str(e):
            return None, ("El token guardado apunta a tu perfil personal y no a tu página. Vuelve a guardar el token "
                          "de Facebook: la app obtiene sola el de la página.")
        return None, str(e)[:300]


_browser_logins: dict[str, subprocess.Popen] = {}


def _browser_state(platform: str) -> dict:
    from agente.publish import browser
    st = browser.status(platform)
    proc = _browser_logins.get(platform)
    running = proc is not None and proc.poll() is None
    return {"connected": bool(st.get("connected")), "pending": running, "error": None if running else st.get("error")}


@app.post("/api/browser-login/{platform}")
def browser_login(platform: str):
    """Abre Chrome (ventana visible) para iniciar sesión una vez; el proceso termina solo al detectar la sesión."""
    from agente.publish import browser
    if platform not in browser.PLATFORMS:
        raise HTTPException(404)
    proc = _browser_logins.get(platform)
    if proc is None or proc.poll() is not None:
        _browser_logins[platform] = subprocess.Popen([sys.executable, "-m", "agente.publish.browser", "login", platform],
                                                     cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                     creationflags=0x08000000)
    return _browser_state(platform)


@app.post("/api/browser-disconnect/{platform}")
def browser_disconnect(platform: str):
    from agente.publish import browser
    if platform not in browser.PLATFORMS:
        raise HTTPException(404)
    proc = _browser_logins.pop(platform, None)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        time.sleep(1)
    browser.disconnect(platform)
    return {"ok": True}


@app.get("/api/connections")
def connections(fresh: bool = False):
    if fresh:  # «Comprobar de nuevo»: no usar resultados guardados
        for k in ("yt_name", "tt_name", "fb_page", "ig_acc"):
            _cache.pop(k, None)
    sec = S.secrets_status()
    out = {"youtube": {"connected": sec["youtube_token"], "name": None, "error": None, "pending": _connect_state["youtube"]},
           "tiktok": {"connected": sec["tiktok_token"], "name": None},
           "facebook": {"connected": sec["facebook_page_token"], "name": None, "error": None},
           "instagram": {"connected": False, "name": None, "error": None}}
    if sec["youtube_token"]:
        from agente.publish import youtube
        out["youtube"]["name"], out["youtube"]["error"] = _cached("yt_name", youtube.status)
    if sec["tiktok_token"]:
        from agente.publish import tiktok
        out["tiktok"]["name"] = _cached("tt_name", tiktok.user_name)
    if sec["facebook_page_token"]:
        out["facebook"]["name"], out["facebook"]["error"] = _cached("fb_page", _fb_page)
        if not out["facebook"]["error"]:  # se revisa aunque Instagram aún no esté guardado como activo
            out["instagram"]["name"], out["instagram"]["error"] = _cached("ig_acc", _ig_account)
            out["instagram"]["connected"] = bool(out["instagram"]["name"])
    p = S.load()["publish"]
    out["browser"] = {k: _browser_state(k) for k in ("youtube", "tiktok", "instagram")}
    out["methods"] = {"youtube": p.get("youtube_method", "browser"), "tiktok": p.get("tiktok_method", "browser")}
    return out


@app.post("/api/connect/youtube")
def connect_youtube():
    if _connect_state["youtube"].get("state") == "waiting":
        return _connect_state["youtube"]
    from agente.publish import youtube

    def work():
        try:
            name = youtube.connect_interactive()
            _cache.pop("yt_name", None)
            _connect_state["youtube"] = {"state": "ok", "msg": f"Conectado: {name}"}
        except Exception as e:
            _connect_state["youtube"] = {"state": "error", "msg": str(e)[:300]}

    _connect_state["youtube"] = {"state": "waiting", "msg": "Autoriza el acceso en la pestaña que se abrió"}
    threading.Thread(target=work, daemon=True).start()
    return _connect_state["youtube"]


@app.get("/api/connect/tiktok")
def connect_tiktok():
    from agente.publish import tiktok
    try:
        return {"url": tiktok.auth_url(REDIRECT_URI)}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/disconnect/{platform}")
def disconnect(platform: str):
    key = {"youtube": "youtube_token", "tiktok": "tiktok_token"}.get(platform)
    if not key:
        raise HTTPException(404)
    S.delete_secret(key)
    _cache.pop("yt_name" if platform == "youtube" else "tt_name", None)
    if platform == "youtube":
        _connect_state["youtube"] = {"state": "idle"}
    return {"ok": True}


def _page(title: str, msg: str, ok: bool) -> HTMLResponse:
    color = "#16a34a" if ok else "#dc2626"
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<body style="font-family:system-ui;background:#0f1115;color:#e7e9ee;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><h2 style="color:{color}">{title}</h2><p>{msg}</p>
<p style="opacity:.6">Puedes cerrar esta pestaña.</p></div>
<script>setTimeout(()=>window.close(),2500)</script></body>""")


@app.get("/callback")
def tiktok_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                    error_description: str | None = None):
    from agente.publish import tiktok
    if error:
        return _page("TikTok no se conectó", error_description or error, False)
    if not code or not state:
        return _page("Solicitud inválida", "Faltan parámetros.", False)
    try:
        tiktok.handle_callback(code, state, REDIRECT_URI)
        _cache.pop("tt_name", None)
        return _page("TikTok conectado", "Ya puedes volver al Agente de Clips.", True)
    except Exception as e:
        return _page("TikTok no se conectó", str(e)[:300], False)


@app.get("/api/voices")
def voices():
    c = _cache.get("voices")
    if c:
        return c[1]
    import edge_tts
    try:
        vs = asyncio.run(edge_tts.list_voices())
    except Exception:
        return []
    from agente import catalog
    out = sorted(({"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"],
                   "label": catalog.voice_label(v["ShortName"]), "country": catalog.locale_label(v["Locale"])}
                  for v in vs if v["Locale"].split("-")[0] in catalog.LANGUAGES),
                 key=lambda v: (v["country"], v["label"]))
    _cache["voices"] = (time.time(), out)
    return out


@app.get("/api/learning")
def get_learning():
    hist = learning.load_history()
    snaps = learning.load_snapshots()
    latest = {}
    for s in snaps:
        k = (s["platform"], s["platform_id"])
        if k not in latest or s["ts"] > latest[k]["ts"]:
            latest[k] = s
    pubs = []
    for h in sorted(hist, key=lambda h: -h["published_at"])[:60]:
        m = latest.get((h["platform"], h["platform_id"]), {})
        pubs.append({**h, "views": m.get("views"), "likes": m.get("likes"), "comments": m.get("comments"),
                     "age_hours": m.get("age_hours")})
    return {"learning": learning.load_learning(), "styles": learning.HOOK_STYLES, "publications": pubs}


@app.post("/api/import-legacy")
def import_legacy(body: dict = Body(default={})):
    imported = []
    cfg_path, cs_path = ROOT / "config.yaml", ROOT / "client_secret.json"
    if cfg_path.is_file():
        import yaml
        c = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        mapping = {
            "youtube_api_key": c.get("youtube", {}).get("api_key"),
            "tiktok_client_key": c.get("tiktok", {}).get("client_key"),
            "tiktok_client_secret": c.get("tiktok", {}).get("client_secret"),
            "facebook_page_token": c.get("facebook", {}).get("page_access_token"),
        }
        for k, v in mapping.items():
            if v:
                S.set_secret(k, str(v))
                imported.append(S.SECRETS[k][0])
        niche = c.get("options", {}).get("niche_query")
        if niche:
            S.save({"content": {"niche": niche}})
    if cs_path.is_file():
        S.set_secret("youtube_client_secret", cs_path.read_text(encoding="utf-8"))
        imported.append(S.SECRETS["youtube_client_secret"][0])
    deleted = []
    if body.get("delete"):
        for p in (cfg_path, cs_path):
            if p.is_file():
                p.unlink()
                deleted.append(p.name)
    return {"imported": imported, "deleted": deleted}


# ── investigación de nicho (para quien empieza) ──────

_niche_job: dict = {"state": "idle", "log": [], "result": None, "error": None}


@app.post("/api/niche-research")
def niche_research_start(body: dict = Body(...)):
    if _niche_job.get("state") == "running":
        return _niche_job
    from agente import niche
    interests = str(body.get("interests", ""))[:300]
    lang = body.get("language") or S.load()["content"]["language"]
    region = body.get("region") or ""

    def work():
        try:
            res = niche.research(S.load(), interests, lang, region, log=lambda m: _niche_job["log"].append(m))
            _niche_job.update(state="done", result=res)
        except Exception as e:
            _niche_job.update(state="error", error=str(e)[:400])

    _niche_job.update(state="running", log=[], result=None, error=None)
    threading.Thread(target=work, daemon=True).start()
    return _niche_job


@app.get("/api/niche-research")
def niche_research_state():
    return _niche_job


@app.post("/api/niche-apply")
def niche_apply(body: dict = Body(...)):
    res = _niche_job.get("result") or {}
    try:
        row = res["niches"][int(body.get("index", -1))]
        patch = json.loads(json.dumps(row["settings"]))
    except (KeyError, IndexError, ValueError, TypeError):
        raise HTTPException(400, "Esa recomendación ya no está disponible; vuelve a investigar.")
    notes = []
    cfg = S.load()
    if patch["video"]["visual_provider"] == "comfyui" and not (cfg["video"].get("comfy_path") or "").strip():
        patch["video"]["visual_provider"] = "pexels"  # sin ComfyUI instalado, video IA local no funcionaría
        notes.append("Se dejó «Clips de stock» porque este PC no tiene ComfyUI configurado (video IA local).")
    saved, fixes = S.save(patch)
    return {"settings": saved, "fixes": fixes + notes}


# ── programación diaria (Programador de tareas de Windows) ──

@app.get("/api/schedule")
def get_schedule():
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"], capture_output=True, text=True,
                       creationflags=0x08000000)
    if r.returncode != 0:
        return {"enabled": False}
    info = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    nxt = next((v for k, v in info.items() if "Next Run" in k or "Próxima" in k), "")
    return {"enabled": True, "next_run": nxt}


@app.put("/api/schedule")
def put_schedule(body: dict = Body(...)):
    if not body.get("enabled"):
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, creationflags=0x08000000)
        return {"enabled": False}
    at = body.get("time", "09:00")
    if len(at) != 5 or at[2] != ":" or not (at[:2] + at[3:]).isdigit():
        raise HTTPException(400, "Hora inválida (HH:MM)")
    script = ROOT / "run_day.ps1"
    tr = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}"'
    r = subprocess.run(["schtasks", "/Create", "/SC", "DAILY", "/TN", TASK_NAME, "/TR", tr, "/ST", at, "/F"],
                       capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode != 0:
        raise HTTPException(500, r.stderr.strip() or r.stdout.strip())
    return get_schedule()


def main():
    import uvicorn
    url = f"http://localhost:{PORT}"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Agente de Clips: {url}  (Ctrl+C para detener)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
