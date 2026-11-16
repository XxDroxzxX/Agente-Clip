"""Imagen («Nano Banana») y video (Veo) con una clave de Gemini aparte, la de la cuenta que tiene esos modelos.

- Personaje consistente: se genera una imagen de referencia del personaje una vez por video y cada imagen clave
  de escena se crea a partir de ella (la cara y la ropa no cambian entre escenas).
- Veo anima esas imágenes clave (imagen→video) o genera desde el texto.

La clave vive en el Administrador de credenciales (`gemini_media_api_key`), separada de la de texto y voz.
"""
from __future__ import annotations

import base64
import random
import time
from pathlib import Path
from typing import Callable

import requests

from . import settings as S

KEY = "gemini_media_api_key"
API = "https://generativelanguage.googleapis.com/v1beta"
IMAGE_PREFERENCE = ["gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-3.1-flash-image-preview",
                    "gemini-3-pro-image-preview", "gemini-2.5-flash-image", "gemini-3.1-flash-lite-image"]
NEGATIVE = "text, watermark, logo, subtitles, deformed face, extra fingers, blurry"


class MediaError(RuntimeError):
    pass


def api_key() -> str:
    k = S.get_secret(KEY)
    if not k:
        raise MediaError("Falta la «Gemini API key (imagen y video)». Agrégala en Configuración → Credenciales.")
    return k


def _explain(r: requests.Response, what: str) -> MediaError:
    try:
        err = r.json().get("error", {})
    except ValueError:
        err = {}
    status, msg = err.get("status", ""), err.get("message", r.text[:200])
    if r.status_code == 429 or status == "RESOURCE_EXHAUSTED":
        quota = " ".join(v.get("quotaId", "") for d in err.get("details", []) for v in d.get("violations", []))
        if "FreeTier" in quota:
            # el plan gratuito de la API no incluye estos modelos (la suscripción Gemini Plus/Pro no se aplica a la API)
            return MediaError(f"{what}: esta clave está en el plan gratuito de la API, que no incluye este modelo. "
                              "La suscripción de la app Gemini no se aplica a la API: hay que activar la facturación "
                              "del proyecto de esa clave en aistudio.google.com → Uso y facturación.")
        return MediaError(f"{what}: se agotó la cuota de este modelo por ahora. Vuelve a intentar más tarde o revisa "
                          "tu plan en aistudio.google.com (Uso y facturación).")
    if r.status_code in (401, 403) or "API key not valid" in msg:
        return MediaError(f"{what}: la clave de imagen y video no es válida o no tiene permiso para este modelo.")
    if status == "INVALID_ARGUMENT" and ("safety" in msg.lower() or "policy" in msg.lower()):
        return MediaError(f"{what}: Google rechazó el contenido por sus políticas; se usará otra vía para esta toma.")
    return MediaError(f"{what}: {msg[:300]}")


def list_models(key: str | None = None) -> dict[str, list[str]]:
    """{"image": [...], "video": [...]} disponibles para la clave (no genera nada ni gasta cuota)."""
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": key or api_key()}, params={"pageSize": 300}, timeout=30)
    if not r.ok:
        raise _explain(r, "Gemini (imagen y video)")
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])]
    return {"image": [n for n in names if "image" in n and "imagen" not in n],
            "video": sorted((n for n in names if n.startswith("veo")), reverse=True)}


def image_model(models: dict | None = None) -> str:
    avail = (models or list_models())["image"]
    for m in IMAGE_PREFERENCE:
        if m in avail:
            return m
    if avail:
        return avail[0]
    raise MediaError("Tu clave no tiene modelos de imagen (Nano Banana).")


def video_model(cfg: dict, models: dict | None = None) -> str:
    want = (cfg["video"].get("veo_model") or "").strip()
    avail = (models or list_models())["video"]
    if want and want in avail:
        return want
    # por defecto la variante «fast» (más barata y rápida) de la versión más nueva
    fast = [m for m in avail if "fast" in m]
    if fast or avail:
        return (fast or avail)[0]
    raise MediaError("Tu clave no tiene modelos de video (Veo).")


def image(prompt: str, out: Path, refs: list[Path] | tuple = (), aspect: str = "9:16", model: str | None = None) -> Path:
    """Genera una imagen; con `refs` (imágenes de referencia) mantiene el mismo personaje."""
    key = api_key()
    parts: list[dict] = [{"text": prompt}]
    for ref in refs:
        mime = "image/png" if Path(ref).suffix.lower() == ".png" else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(Path(ref).read_bytes()).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}
    model = model or image_model()
    for attempt in range(3):
        r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body,
                          timeout=180)
        if r.status_code >= 500 and attempt < 2:
            time.sleep(8 * (attempt + 1))
            continue
        if not r.ok:
            raise _explain(r, "Nano Banana")
        cand = (r.json().get("candidates") or [{}])[0]
        inline = next((p["inlineData"] for p in (cand.get("content") or {}).get("parts", []) if "inlineData" in p), None)
        if not inline:
            raise MediaError(f"Nano Banana no devolvió imagen ({cand.get('finishReason', 'sin motivo')}).")
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(inline["data"])
        if out.suffix.lower() == ".png" and not raw.startswith(b"\x89PNG"):
            # Veo y ComfyUI deducen el formato por la extensión: se convierte a PNG de verdad
            from . import ffmpeg
            tmp = out.with_suffix(".src")
            tmp.write_bytes(raw)
            ffmpeg.run(["-i", tmp, "-frames:v", "1", out])
            tmp.unlink(missing_ok=True)
        else:
            out.write_bytes(raw)
        return out
    raise MediaError("Nano Banana no respondió (servidores saturados).")


def character_sheet(bible: str, out: Path, aspect: str, style: str = "") -> Path:
    """Imagen de referencia del personaje principal (una por video)."""
    prompt = (f"Character reference image: {bible.strip()} Show the main character clearly, front-facing, full face "
              f"and outfit visible, neutral pose, plain background matching the setting. {style}. "
              f"Photorealistic consistent design, no text.")
    return image(prompt, out, aspect=aspect)


def scene_keyframe(prompt: str, character: Path | None, out: Path, aspect: str) -> Path:
    """Imagen clave de una escena manteniendo al personaje de la referencia."""
    text = (f"{prompt.strip()} Keep exactly the same character as in the reference image (same face, hair, age and "
            f"clothes). Cinematic frame, no text." if character else f"{prompt.strip()} Cinematic frame, no text.")
    return image(text, out, refs=[character] if character else (), aspect=aspect)


class VeoVideo:
    """Video IA con Veo (Gemini API). Misma interfaz que ComfyVideo/FalVideo."""
    DURATIONS = (4, 6, 8)

    def __init__(self, cfg: dict, portrait: bool):
        self.key = api_key()
        self.models = list_models(self.key)
        self.model = video_model(cfg, self.models)
        self.aspect = "9:16" if portrait else "16:9"
        self.segment = 8.0
        self.style = (cfg["video"].get("ai_style") or "").strip()

    def generate(self, prompt: str, start_frame: Path | None, dest: Path, log: Callable[[str], None],
                 seconds: float | None = None) -> Path:
        if self.style:
            prompt = f"{prompt.rstrip('. ')}. {self.style}"
        dur = next((d for d in self.DURATIONS if d >= (seconds or 8) - 0.05), 8)
        inst: dict = {"prompt": prompt}
        if start_frame is not None:
            mime = "image/png" if start_frame.suffix.lower() == ".png" else "image/jpeg"
            inst["image"] = {"bytesBase64Encoded": base64.b64encode(start_frame.read_bytes()).decode(), "mimeType": mime}
        body = {"instances": [inst], "parameters": {"aspectRatio": self.aspect, "durationSeconds": dur,
                                                     "negativePrompt": NEGATIVE, "seed": random.randint(1, 2**31 - 1)}}
        t0 = time.time()
        r = requests.post(f"{API}/models/{self.model}:predictLongRunning", headers={"x-goog-api-key": self.key},
                          json=body, timeout=120)
        if not r.ok:
            raise _explain(r, "Veo")
        name = r.json()["name"]
        while True:
            time.sleep(10)
            op = requests.get(f"{API}/{name}", headers={"x-goog-api-key": self.key}, timeout=60).json()
            if op.get("done"):
                break
            if time.time() - t0 > 900:
                raise MediaError("Veo tardó más de 15 minutos en una toma.")
        if "error" in op:
            raise MediaError(f"Veo no pudo generar la toma: {op['error'].get('message', '')[:300]}")
        samples = ((op.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or []
        uri = (samples[0].get("video") or {}).get("uri") if samples else None
        if not uri:
            raise MediaError("Veo terminó sin video (puede haberlo filtrado por sus políticas de contenido).")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(uri, headers={"x-goog-api-key": self.key}, stream=True, timeout=300) as v:
            v.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in v.iter_content(1 << 20):
                    f.write(chunk)
        log(f"Toma Veo ({self.model}, {dur} s) lista en {(time.time() - t0) / 60:.1f} min.")
        return dest

    def release(self) -> None:
        pass


def sheet_prompt(bible: str, style: str = "") -> str:
    return (f"Character reference image: {bible.strip()} Show the main character clearly, front-facing, full face "
            f"and outfit visible, neutral pose, plain background matching the setting. {style}. "
            f"Photorealistic consistent design, no text.")


def scene_prompt(prompt: str, with_ref: bool) -> str:
    return (f"{prompt.strip()} Keep exactly the same character as in the reference image (same face, hair, age and "
            f"clothes). Cinematic frame, no text." if with_ref else f"{prompt.strip()} Cinematic frame, no text.")


def attach_character(ai, bible: str, out_dir: Path, portrait: bool, style: str, log, engine: str = "auto") -> bool:
    """Hace que las imágenes clave del proveedor mantengan al personaje de una imagen de referencia.
    engine: «local» (Qwen-Image-Edit en ComfyUI, gratis), «nanobanana» (clave de imagen de Gemini) o «auto»
    (local si está instalado y el proveedor es ComfyUI; si no, Nano Banana). True si quedó activo; si falla, el
    proveedor sigue con sus propias imágenes clave."""
    aspect = "9:16" if portrait else "16:9"
    ref = out_dir / "character.png"
    local = hasattr(ai, "edit_image") and engine in ("auto", "local")
    if engine == "local" and not local:
        log("Personaje consistente local: requiere ComfyUI como proveedor de video.", "warn")
        return False
    if not local and not S.get_secret(KEY):
        return False
    name = "Qwen-Image-Edit (local)" if local else "Nano Banana"
    try:
        if not (ref.is_file() and ref.stat().st_size > 0):
            log(f"Personaje: creando la imagen de referencia con {name}…", "info")
            if local:
                ai.edit_image(sheet_prompt(bible, style), None, ref, lambda m: log(m, "info"))
            else:
                character_sheet(bible, ref, aspect, style)
    except Exception as e:
        log(f"Personaje consistente no disponible ({str(e)[:200]}); se sigue sin referencia.", "warn")
        return False

    def keyframe(prompt: str, dest: Path, log_fn) -> Path:
        if local:
            return ai.edit_image(scene_prompt(prompt, True), ref, dest, log_fn)
        return scene_keyframe(prompt, ref, dest, aspect)

    ai.keyframe = keyframe
    ai.character_local = local  # el pipeline genera primero todas las imágenes clave (una sola carga de modelos)
    log(f"Personaje consistente activo con {name}: cada escena parte de la misma referencia.", "info")
    return True
