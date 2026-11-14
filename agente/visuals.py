"""Material visual por toma.

Proveedores:
  - stock:  clips de video reales de Pexels y/o Pixabay (gratis, requieren API key;
            se usan los que tengan clave, en ese orden).
  - fal / comfyui: video generado por IA (fal.ai en la nube o ComfyUI local en la GPU).
            Cada toma parte del ÚLTIMO FOTOGRAMA de la anterior (image-to-video), así la
            secuencia tiene continuidad visual. Con ComfyUI se puede limitar la IA a las
            primeras tomas (el gancho) y usar stock en el resto.
Respaldo: foto de stock con movimiento (Ken Burns) o fondo de color.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from . import ffmpeg
from . import settings as S
from .paths import CACHE_DIR

SHOT_SECONDS = 5.0  # duración objetivo de cada toma (ritmo de cortes)


@dataclass
class Shot:
    scene: int
    duration: float
    query: str
    prompt: str
    text: str = ""            # narración de la escena
    source: Path | None = None
    kind: str = "color"      # video | image | color
    credit: str = ""
    anim: dict | None = None  # animación Remotion a superponer
    overlay: Path | None = None
    punch: float = 0.0        # acercamiento rápido al inicio de la toma (0 = no; 0.06 = 6 %)
    bible: str = ""           # ficha visual del video (personaje, lugar, estilo) para el generador IA
    chained: bool = False     # la toma IA continúa desde el último cuadro de la anterior


def plan_shots(scenes: list, durations: list[float], bible: str = "") -> list[Shot]:
    shots = []
    for i, (sc, d) in enumerate(zip(scenes, durations)):
        anim = getattr(sc, "animation", None)
        anim = anim.model_dump() if anim is not None and hasattr(anim, "model_dump") else anim
        # una escena animada es una sola toma: la animación sigue a la voz durante toda la escena
        n = 1 if anim else max(1, round(d / SHOT_SECONDS))
        for k in range(n):
            shots.append(Shot(scene=i, duration=d / n, query=sc.visual_query, prompt=sc.visual_prompt,
                              text=sc.narration, anim=anim if k == 0 else None, bible=bible))
    return shots


# ── Pexels ────────────────────────────────────────────

class Pexels:
    API = "https://api.pexels.com"

    def __init__(self, key: str, portrait: bool, min_side: int):
        self.s = requests.Session()
        self.s.headers["Authorization"] = key
        self.orientation = "portrait" if portrait else "landscape"
        self.min_side = min_side
        self.used: set[int] = set()
        self._cache: dict[str, list] = {}

    name = "Pexels"

    def _get(self, path: str, **params):
        r = self.s.get(f"{self.API}{path}", params=params, timeout=30)
        check_status(self.name, r, "200 por hora")
        return r.json()

    def videos(self, query: str) -> list:
        if query not in self._cache:
            data = self._get("/videos/search", query=query, orientation=self.orientation, per_page=15, size="medium")
            self._cache[query] = data.get("videos", [])
        return self._cache[query]

    def _best_file(self, video: dict) -> dict | None:
        files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        if not files:
            return None
        side = (lambda f: f["width"]) if self.orientation == "portrait" else (lambda f: f["height"])
        good = [f for f in files if side(f) >= self.min_side]
        return min(good, key=side) if good else max(files, key=side)

    def candidates(self, query: str, min_dur: float, k: int) -> list["Cand"]:
        out: list[Cand] = []
        for q in _query_variants(query):
            for v in self.videos(q):
                if v["id"] in self.used or v.get("duration", 0) < min(min_dur, 4):
                    continue
                f = self._best_file(v)
                if not f or any(c.id == v["id"] for c in out):
                    continue
                out.append(Cand(self, v["id"], f["link"], v.get("image") or "", f["width"], f["height"],
                                v.get("duration", 0), f"Video de {v.get('user', {}).get('name', 'Pexels')} en Pexels"))
                if len(out) >= k:
                    return out
        return out

    def find_video(self, query: str, min_dur: float) -> tuple[Path, str] | None:
        c = self.candidates(query, min_dur, 1)
        return (c[0].fetch(), c[0].credit) if c else None

    def find_photo(self, query: str) -> tuple[Path, str] | None:
        data = self._get("/v1/search", query=query, orientation=self.orientation, per_page=10)
        for p in data.get("photos", []):
            if p["id"] in self.used:
                continue
            self.used.add(p["id"])
            dest = CACHE_DIR / "pexels" / f"photo_{p['id']}.jpg"
            if not dest.exists():
                _download(p["src"]["large2x"], dest)
            return dest, f"Foto de {p.get('photographer', 'Pexels')} en Pexels"
        return None


class Pixabay:
    """API gratuita de pixabay.com (videos hasta 4K). Pide guardar las búsquedas 24 h."""
    API = "https://pixabay.com/api"
    name = "Pixabay"
    CACHE_TTL = 24 * 3600

    def __init__(self, key: str, portrait: bool, min_side: int):
        self.key = key
        self.portrait = portrait
        self.min_side = min_side
        self.used: set[int] = set()

    def _get(self, path: str, **params):
        params = {"safesearch": "true", **params}
        h = hashlib.sha1(json.dumps([path, params], sort_keys=True).encode()).hexdigest()[:16]
        cache = CACHE_DIR / "pixabay" / "search" / f"{h}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < self.CACHE_TTL:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except ValueError:
                pass
        r = requests.get(f"{self.API}{path}", params={"key": self.key, **params}, timeout=30)
        check_status(self.name, r, "100 por minuto")
        data = r.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _rendition(self, hit: dict) -> dict | None:
        files = [f for f in (hit.get("videos") or {}).values() if f.get("url") and f.get("width")]
        if not files:
            return None
        side = lambda f: min(f["width"], f["height"])
        good = [f for f in files if side(f) >= self.min_side]
        return min(good, key=side) if good else max(files, key=side)

    def _fits(self, hit: dict) -> bool:
        f = (hit.get("videos") or {}).get("small") or {}
        return (f.get("height", 0) > f.get("width", 0)) == self.portrait

    def candidates(self, query: str, min_dur: float, k: int) -> list["Cand"]:
        out: list[Cand] = []
        for q in _query_variants(query):
            hits = self._get("/videos/", q=q[:100], per_page=20, video_type="film").get("hits", [])
            # Pixabay no filtra por orientación: primero los que coinciden (el resto se recorta)
            for v in sorted(hits, key=lambda h: not self._fits(h)):
                if v["id"] in self.used or v.get("duration", 0) < min(min_dur, 4):
                    continue
                f = self._rendition(v)
                if not f or any(c.id == v["id"] for c in out):
                    continue
                vids = v.get("videos") or {}
                thumb = next((vids[s].get("thumbnail") for s in ("small", "medium", "tiny")
                              if (vids.get(s) or {}).get("thumbnail")), "")
                out.append(Cand(self, v["id"], f["url"], thumb, f["width"], f["height"], v.get("duration", 0),
                                f"Video de {v.get('user') or 'Pixabay'} en Pixabay"))
                if len(out) >= k:
                    return out
        return out

    def find_video(self, query: str, min_dur: float) -> tuple[Path, str] | None:
        c = self.candidates(query, min_dur, 1)
        return (c[0].fetch(), c[0].credit) if c else None

    def find_photo(self, query: str) -> tuple[Path, str] | None:
        data = self._get("/", q=query[:100], image_type="photo", per_page=10,
                         orientation="vertical" if self.portrait else "horizontal")
        for p in data.get("hits", []):
            if p["id"] in self.used or not p.get("largeImageURL"):
                continue
            self.used.add(p["id"])
            dest = CACHE_DIR / "pixabay" / f"photo_{p['id']}.jpg"
            if not dest.exists():
                _download(p["largeImageURL"], dest)
            return dest, f"Foto de {p.get('user') or 'Pixabay'} en Pixabay"
        return None


@dataclass
class Cand:
    """Clip candidato de un banco de stock."""
    src: object
    id: int
    url: str
    thumb_url: str
    width: int
    height: int
    duration: float
    credit: str

    @property
    def key(self) -> str:
        return f"{self.src.name}:{self.id}"

    def fetch(self) -> Path:
        self.src.used.add(self.id)
        dest = CACHE_DIR / self.src.name.lower() / f"{self.id}_{self.width}x{self.height}.mp4"
        if not dest.exists():
            _download(self.url, dest)
        return dest

    def thumb(self) -> Path | None:
        """Miniatura reducida (máx. 320 px) para la IA con visión."""
        if not self.thumb_url:
            return None
        dest = CACHE_DIR / "thumbs" / f"{self.src.name.lower()}_{self.id}.jpg"
        if dest.exists():
            return dest
        try:
            raw = dest.with_suffix(".src")
            _download(self.thumb_url, raw)
            ffmpeg.run(["-i", raw, "-vf", "scale='if(gt(iw,ih),320,-2)':'if(gt(iw,ih),-2,320)'",
                        "-frames:v", "1", "-q:v", "4", dest])
            raw.unlink(missing_ok=True)
            return dest
        except Exception:
            return None


def _query_variants(query: str) -> list[str]:
    return list(dict.fromkeys(q for q in (query, " ".join(query.split()[:2])) if q.strip()))


def check_status(name: str, r: requests.Response, limit: str):
    """Convierte errores HTTP de las APIs de stock en mensajes entendibles."""
    if r.ok:
        return
    code = r.status_code
    if code in (401, 403) or (code == 400 and "key" in r.text.lower()):
        raise RuntimeError(f"{name}: la API key no es válida. Revísala en Configuración → Credenciales.")
    if code == 429:
        raise RuntimeError(f"{name}: se alcanzó el límite de solicitudes ({limit}). Espera unos minutos.")
    if code >= 500:
        raise RuntimeError(f"{name} no está disponible en este momento (error {code}). Intenta más tarde.")
    raise RuntimeError(f"{name} rechazó la búsqueda (error {code}).")


def stock_sources(portrait: bool, min_side: int) -> list:
    out = []
    for cls, secret in ((Pexels, "pexels_api_key"), (Pixabay, "pixabay_api_key")):
        key = S.get_secret(secret)
        if key:
            out.append(cls(key, portrait, min_side))
    return out


def _from_stock(sources: list, kind: str, query: str, min_dur: float, log) -> tuple[Path, str] | None:
    for src in list(sources):
        try:
            found = src.find_video(query, min_dur) if kind == "video" else src.find_photo(query)
        except Exception as e:  # una fuente caída no detiene a las demás
            if "no es válida" in str(e):
                sources.remove(src)  # no insistir con una clave mala en cada toma
                log(f"{e} Se omite {src.name} en este run.", "warn")
            else:
                log(str(e), "warn")
            continue
        if found:
            return found
    return None


def _gather(sources: list, query: str, min_dur: float, k: int, log) -> list[Cand]:
    out: list[Cand] = []
    for src in list(sources):
        try:
            out += src.candidates(query, min_dur, k - len(out))
        except Exception as e:
            if "no es válida" in str(e):
                sources.remove(src)
                log(f"{e} Se omite {src.name} en este run.", "warn")
            else:
                log(str(e), "warn")
        if len(out) >= k:
            break
    return out


def assign_stock(shots: list[Shot], sources: list, cfg: dict, portrait: bool,
                 log: Callable[[str, str], None], progress: Callable[[float], None],
                 broll: list[str] | tuple = ()) -> None:
    """Busca candidatos por escena, deja que una IA con visión los ordene (si está disponible)
    y asigna a cada toma el mejor clip que no se haya usado antes en el video."""
    from . import vision
    scenes: dict[int, list[Shot]] = {}
    for sh in shots:
        scenes.setdefault(sh.scene, []).append(sh)
    smart = vision.provider(cfg) is not None
    cands: dict[int, list[Cand]] = {}
    for n, (i, group) in enumerate(scenes.items()):
        k = len(group) + (3 if smart else 1)
        cands[i] = _gather(sources, group[0].query, max(s.duration for s in group), k, log)
        progress(0.4 * (n + 1) / len(scenes))
    order: dict[int, list[int]] = {}
    if smart:
        req = [{"scene": i, "narration": scenes[i][0].text, "query": scenes[i][0].query,
                "thumbs": [c.thumb() for c in cs]} for i, cs in cands.items() if len(cs) > 1]
        order = vision.rank_scenes(cfg, req, portrait, log)
    progress(0.5)
    # con visión solo entran los clips que la IA aprobó: lo descartado no se usa de relleno
    seqs: dict[int, list[Cand]] = {}
    for i, cs in cands.items():
        seqs[i] = [cs[j] for j in order[i] if 0 <= j < len(cs)] if i in order else list(cs)
    lacking = [i for i, g in scenes.items() if i in order and len(seqs.get(i, [])) < len(g)]
    if lacking and broll:
        pool: list[Cand] = []
        seen: set[str] = set()
        for q in broll[:5]:
            for c in _gather(sources, q, 4.0, 5, log):
                if c.key not in seen:
                    seen.add(c.key)
                    pool.append(c)
        pool = pool[:vision.MAX_IMAGES_PER_CALL]
        picks = vision.rank_pool(cfg, [{"scene": i, "narration": scenes[i][0].text} for i in lacking],
                                 [c.thumb() for c in pool], portrait, log)
        added = 0
        for i in lacking:
            extra = [pool[j] for j in picks.get(i, []) if 0 <= j < len(pool)]
            seqs[i] += extra
            added += len(extra)
        if added:
            log(f"{len(lacking)} escenas sin clip adecuado: se completaron con tomas genéricas del nicho.", "info")
    for i, group in list(scenes.items()):
        ok = len(seqs.get(i, []))
        if i not in order or ok >= len(group):
            continue
        if ok == 0:  # último recurso: lo mejor que haya, avisando
            seqs[i] = list(cands.get(i, []))
            log(f"Escena {i + 1}: ningún clip encaja con «{group[0].query}»; se usa el mejor disponible.", "warn")
            continue
        # faltan clips aprobados: las tomas de la escena se funden (mejor menos cortes que algo sin relación)
        keep, drop = group[:ok], group[ok:]
        extra = sum(s.duration for s in drop)
        for s in keep:
            s.duration += extra / len(keep)
        for s in drop:
            shots.remove(s)
        scenes[i] = keep
    used: set[str] = set()
    for n, (i, group) in enumerate(scenes.items()):
        seq = seqs.get(i, [])
        for sh in group:
            for c in seq:
                if c.key in used:
                    continue
                try:
                    sh.source, sh.credit, sh.kind = c.fetch(), c.credit, "video"
                    used.add(c.key)
                    break
                except Exception as e:
                    log(f"No se pudo descargar un clip ({e}); se prueba otro.", "warn")
            if sh.source is None:
                photo = _from_stock(sources, "photo", sh.query, 0, log)
                if photo:
                    sh.source, sh.credit = photo
                    sh.kind = "image"
                    log(f"Sin video para «{sh.query}»; se usa foto con movimiento.", "warn")
                else:
                    log(f"Sin material para «{sh.query}»; se usa fondo de color.", "warn")
        progress(0.5 + 0.5 * (n + 1) / len(scenes))


def _download(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)


# ── fal.ai (video IA encadenado) ──────────────────────

class FalVideo:
    QUEUE = "https://queue.fal.run"

    def __init__(self, key: str, cfg: dict, portrait: bool):
        v = cfg["video"]
        self.h = {"Authorization": f"Key {key}"}
        self.t2v, self.i2v = v["fal_t2v_model"], v["fal_i2v_model"]
        self.aspect = "9:16" if portrait else "16:9"
        self.segment = float(v.get("fal_segment_seconds", 5))
        self.style = (v.get("ai_style") or "").strip()

    def _run(self, model: str, payload: dict, log: Callable[[str], None]) -> str:
        r = requests.post(f"{self.QUEUE}/{model}", json=payload, headers=self.h, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"fal.ai ({model}) rechazó la solicitud: {r.status_code} {r.text[:300]}")
        job = r.json()
        status_url, response_url = job["status_url"], job["response_url"]
        t0 = time.time()
        while True:
            st = requests.get(status_url, headers=self.h, timeout=30).json()
            status = st.get("status")
            if status == "COMPLETED":
                break
            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise RuntimeError(f"fal.ai devolvió estado inesperado: {st}")
            if time.time() - t0 > 900:
                raise RuntimeError("fal.ai tardó más de 15 minutos en una toma.")
            time.sleep(4)
        out = requests.get(response_url, headers=self.h, timeout=60).json()
        video = out.get("video") or {}
        if not video.get("url"):
            raise RuntimeError(f"fal.ai no devolvió video: {str(out)[:300]}")
        return video["url"]

    def generate(self, prompt: str, start_frame: Path | None, dest: Path, log: Callable[[str], None],
                 seconds: float | None = None) -> Path:
        if self.style:
            prompt = f"{prompt.rstrip('. ')}. {self.style}"
        payload = {"prompt": prompt, "aspect_ratio": self.aspect}
        if start_frame is not None:
            b64 = base64.b64encode(start_frame.read_bytes()).decode()
            payload["image_url"] = f"data:image/jpeg;base64,{b64}"
            url = self._run(self.i2v, payload, log)
        else:
            url = self._run(self.t2v, payload, log)
        _download(url, dest)
        return dest




# ── orquestación por item ─────────────────────────────

def ai_provider(cfg: dict, portrait: bool, log: Callable[[str, str], None]):
    """Generador de video IA según la configuración, o None (con aviso) si no se puede usar."""
    prov = cfg["video"]["visual_provider"]
    if prov == "fal":
        key = S.get_secret("fal_api_key")
        if not key:
            log("Proveedor fal.ai seleccionado pero falta la API key; se usan clips de stock.", "warn")
            return None
        return FalVideo(key, cfg, portrait)
    if prov == "comfyui":
        from .comfyui import ComfyVideo
        try:
            ai = ComfyVideo(cfg, portrait)
            ai.ensure_running(lambda m: log(m, "info"))
            return ai
        except Exception as e:
            log(f"{e} Se usan clips de stock.", "warn")
            return None
    return None


def ai_shot_ids(shots: list[Shot], cfg: dict) -> list[int]:
    """Índices de las tomas que van con IA. Con ComfyUI se puede limitar a las primeras N (el gancho)."""
    v = cfg["video"]
    n = int(v.get("comfy_max_shots", 0) or 0) if v["visual_provider"] == "comfyui" else 0
    return list(range(len(shots) if n <= 0 else min(n, len(shots))))


def last_frame(video: Path, out: Path) -> Path:
    """Último cuadro exacto, sin pérdida (PNG): en una cadena larga el JPEG acumularía artefactos en cada empalme."""
    ffmpeg.run(["-sseof", "-1", "-i", video, "-update", "1", "-an", out])
    return out


def ai_prompt(shot: Shot) -> str:
    return f"{shot.prompt.rstrip('. ')}. {shot.bible}".strip() if shot.bible else shot.prompt


def _make_segment(ai, prompt: str, start: Path | None, dest: Path, seconds: float, log) -> None:
    raw = dest.with_name(dest.stem + "_raw.mp4")
    ai.generate(prompt, start, raw, lambda m: log(m, "info"), seconds=seconds)
    if start is not None:
        # el 1.er cuadro repite el último de la toma anterior: se quita para que el empalme no se congele
        ffmpeg.run(["-i", raw, "-vf", "trim=start_frame=1,setpts=PTS-STARTPTS", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", dest])
        raw.unlink(missing_ok=True)
    else:
        raw.replace(dest)


def _director(cfg: dict, log) -> Callable | None:
    """Revisor con visión de cada segmento IA (si está activado y hay proveedor)."""
    from . import vision
    v = cfg["video"]
    if v["visual_provider"] != "comfyui" or not v.get("comfy_director", True) or not vision.provider(cfg):
        return None
    min_score = int(v.get("comfy_director_min", 6))

    def judge(shot: Shot, clip: Path, seconds: float, prompt: str):
        frames = [ffmpeg.extract_frame(clip, clip.with_name(clip.stem + "_mid.jpg"), at=seconds / 2, width=384),
                  ffmpeg.extract_frame(clip, clip.with_name(clip.stem + "_end.jpg"), last=True, width=384)]
        verdict = vision.judge_shot(cfg, frames, shot.text, prompt, log)
        for f in frames:
            f.unlink(missing_ok=True)
        if verdict is None or verdict.score >= min_score:
            return None
        return verdict
    return judge


def _generate_ai(ai, shot: Shot, i: int, prev_clip: Path | None, out_dir: Path,
                 log: Callable[[str, str], None], judge: Callable | None = None) -> Path:
    """Genera una toma (en uno o más segmentos encadenados) y devuelve el último segmento."""
    parts = max(1, math.ceil(shot.duration / ai.segment - 0.15))  # tolera tomas apenas más largas que un segmento
    seconds = shot.duration / parts
    prompt = ai_prompt(shot)
    shot.chained = prev_clip is not None
    clips = []
    for k in range(parts):
        dest = out_dir / f"ai_{i:03d}_{k}.mp4"
        if dest.is_file() and dest.stat().st_size > 0:  # «Reintentar» reutiliza lo ya generado
            log(f"IA: toma {i+1}.{k+1} reutilizada.", "info")
        else:
            start = last_frame(prev_clip, out_dir / f"frame_{i:03d}_{k}.png") if prev_clip is not None else None
            log(f"IA: generando toma {i+1}.{k+1} {'desde el último fotograma' if start else 'inicial'}", "info")
            _make_segment(ai, prompt, start, dest, seconds, log)
            bad = judge(shot, dest, seconds, prompt) if judge else None
            if bad is not None:
                # se desvió de la escena: una sola regeneración, desde cero y con el prompt corregido
                log(f"Director IA: toma {i+1}.{k+1} con nota {bad.score}/10 ({bad.issue}); se regenera desde cero.", "warn")
                if bad.better_prompt.strip():
                    prompt = f"{bad.better_prompt.strip().rstrip('. ')}. {shot.bible}".strip()
                _make_segment(ai, prompt, None, dest, seconds, log)
                if k == 0:
                    shot.chained = False
        clips.append(dest)
        prev_clip = dest
    if len(clips) == 1:
        shot.source = clips[0]
    else:
        joined = out_dir / f"ai_{i:03d}.mp4"
        lst = out_dir / f"ai_{i:03d}.txt"
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
        ffmpeg.run(["-f", "concat", "-safe", "0", "-i", lst.name, "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "16", "-pix_fmt", "yuv420p", joined.name], cwd=out_dir)  # segmentos de distinto origen
        shot.source = joined
    shot.kind, shot.credit = "video", "Generado con IA"
    return prev_clip


def fetch_for_item(shots: list[Shot], portrait: bool, min_side: int, cfg: dict, use_ai: bool,
                   out_dir: Path, log: Callable[[str, str], None], progress: Callable[[float], None],
                   broll: list[str] | tuple = ()):
    """Asigna material a cada toma. Modifica `shots` en el lugar (la selección de stock puede fundir tomas)."""
    stock = stock_sources(portrait, min_side)
    ai = ai_provider(cfg, portrait, log) if use_ai else None
    if not stock and not ai:
        log("Sin fuente de clips configurada: se usarán fondos de color. "
            "Agrega la API key de Pixabay o Pexels en Configuración.", "warn")

    # índice original de cada toma IA: nombra sus archivos de forma estable para «Reintentar»
    ai_idx = {id(shots[i]): i for i in ai_shot_ids(shots, cfg)} if ai else {}
    rest = [s for s in shots if id(s) not in ai_idx]
    share = len(rest) / max(1, len(shots))
    if rest and stock:
        assign_stock(rest, stock, cfg, portrait, log, lambda p: progress(p * share), broll)
        keep = {id(s) for s in rest} | set(ai_idx)
        shots[:] = [s for s in shots if id(s) in keep]
    if not ai:
        return shots

    log(f"IA: {len(ai_idx)} toma(s) con video generado"
        + (f"; {len(shots) - len(ai_idx)} con clips de stock." if len(shots) > len(ai_idx) else "."), "info")
    by_scene = cfg["video"].get("comfy_chain", "scene") == "scene" and cfg["video"]["visual_provider"] == "comfyui"
    judge = _director(cfg, log)
    prev_clip: Path | None = None
    prev_scene: int | None = None
    done = 0
    try:
        for shot in shots:
            i = ai_idx.get(id(shot))
            if i is None:
                prev_clip = None  # la cadena solo sigue entre tomas IA consecutivas
                continue
            if by_scene and shot.scene != prev_scene:
                prev_clip = None  # escena nueva: arranca desde el texto (corte), así vuelve a seguir la narración
            prev_scene = shot.scene
            try:
                prev_clip = _generate_ai(ai, shot, i, prev_clip, out_dir, log, judge)
            except Exception as e:
                log(f"Toma {i+1}: {e}. Se usa respaldo.", "warn")
                prev_clip = None  # reinicia la cadena
                found = _from_stock(stock, "video", shot.query, shot.duration, log) if stock else None
                if found:
                    shot.source, shot.credit = found
                    shot.kind = "video"
            done += 1
            progress(share + (1 - share) * done / len(ai_idx))
    finally:
        release = getattr(ai, "release", None)
        if release:
            release()
    return shots
