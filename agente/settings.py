"""Configuración del agente.

- Opciones no sensibles -> data/settings.json
- Credenciales (tokens, claves) -> Administrador de credenciales de Windows (keyring).
  Nunca se escriben en archivos del proyecto ni se devuelven al navegador.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import keyring
from keyring.errors import PasswordDeleteError

from .paths import SETTINGS_FILE
from .util import atomic_write_text

KEYRING_SERVICE = "AgenteDeClips"
_CHUNK = 1000  # el Administrador de credenciales limita el tamaño de cada entrada

# name -> (etiqueta, ayuda)
SECRETS: dict[str, tuple[str, str]] = {
    "anthropic_api_key": ("Claude API key", "console.anthropic.com → API Keys (facturación aparte de la suscripción Pro)"),
    "gemini_api_key": ("Gemini API key", "Gratis y sin tarjeta: aistudio.google.com → Get API key. Sirve para guiones y para elegir clips con visión. En el plan gratuito Google puede usar los datos enviados para mejorar sus productos"),
    "pixabay_api_key": ("Pixabay API key", "Gratis: crea una cuenta en pixabay.com y copia tu clave desde pixabay.com/api/docs — clips de video por escena"),
    "pexels_api_key": ("Pexels API key", "Opcional, gratis en pexels.com/api (Pexels pausó la emisión de claves nuevas; con Pixabay basta)"),
    "fal_api_key": ("fal.ai API key", "Opcional, de pago — video generado por IA encadenando fotogramas"),
    "youtube_api_key": ("YouTube Data API key", "Google Cloud Console → Credenciales → Clave de API"),
    "youtube_client_secret": ("YouTube OAuth client (JSON)", "Contenido de client_secret.json (app de escritorio)"),
    "tiktok_client_key": ("TikTok client key", "developers.tiktok.com → tu app"),
    "tiktok_client_secret": ("TikTok client secret", "developers.tiktok.com → tu app"),
    "facebook_page_token": ("Facebook Page access token", "Token de página con pages_manage_posts y publish_video"),
}
# Tokens obtenidos por OAuth (no se editan a mano)
OAUTH_TOKENS = ("youtube_token", "tiktok_token")

DEFAULTS: dict[str, Any] = {
    "content": {
        "niche": "cocina vegana",
        "language": "es",
        "region_code": "",          # p.ej. "MX", "CO", "ES"; vacío = global
        "research_days": 30,
        "audience": "público hispanohablante general",
        "extra_instructions": "",
    },
    "llm": {
        "provider": "claude",       # claude | gemini | ollama
        "claude_model": "claude-opus-5-5",
        "claude_effort": "medium",
        "ollama_url": "http://localhost:11434",
        "ollama_model": "qwen2.5:7b",
        "gemini_model": "gemini-4-hydrogen",
    },
    "video": {
        "long_enabled": True,
        "long_minutes": 3,
        "shorts_count": 2,
        "quality": "1080p",         # 1080p | 720p
        "visual_provider": "pexels",  # pexels | fal | comfyui
        "fal_scope": "shorts",      # shorts | all (también vale para ComfyUI)
        "fal_t2v_model": "fal-ai/wan-t2v",
        "fal_i2v_model": "fal-ai/wan-i2v",
        "fal_segment_seconds": 5,
        "ai_style": "",             # texto que se agrega a cada prompt IA, p. ej. «cinematic, film grain» o «anime style»
        # ComfyUI local (video IA en la GPU del PC)
        "comfy_url": "http://127.0.0.1:8188",
        "comfy_path": "",           # carpeta de ComfyUI portable: si no está abierto, el run lo inicia y lo cierra al final
        "comfy_workflow": "wan22_ti2v_5b.json",  # en agente/workflows/ o ruta absoluta (formato API)
        "comfy_resolution": "480p",  # 480p (6-8 GB VRAM) | 544p | 704p (nativa de Wan 2.2 5B, pide más VRAM)
        "comfy_steps": 20,
        "comfy_fps": 24,
        "comfy_segment_seconds": 5,
        "comfy_max_shots": 2,       # tomas IA por video (las primeras = el gancho); 0 = todas
        "comfy_timeout_min": 30,
        "subtitles": True,
        "music": True,
        "music_volume": 0.12,
        "music_source": "generada",  # generada (gratis) | lyria (Gemini, de pago) | carpeta (assets/music)
        "smart_clips": "auto",      # auto | gemini | claude | off — IA con visión elige los clips
        "animations": True,         # capas animadas con Remotion
        "anim_color": "#FFD633",    # color de resaltado de las animaciones
        "sfx": True,                # whoosh con las animaciones y en los cambios de escena
        "transitions": True,
        "thumbnail": True,          # miniatura personalizada (Remotion) para el video largo
        "review": "auto",           # auto | gemini | claude | off — revisión de calidad con IA tras el montaje
        "review_block": True,       # la publicación automática se salta los videos reprobados
        "review_min_score": 6,        # acercamiento rápido («punch-in») al cambiar de escena
    },
    "voice": {
        "engine": "edge",           # edge (Microsoft, tiempos exactos) | gemini (Gemini TTS, más expresiva)
        "name": "es-MX-JorgeNeural",
        "rate": "+6%",
        "gemini_voice": "Puck",
        "gemini_style": "cercano y con energía, como un creador de contenido latino, ritmo ágil",
    },
    "publish": {
        "auto_publish": False,
        "youtube": True,
        "youtube_privacy": "private",   # private | unlisted | public
        "youtube_category": "26",       # 26 = Howto & Style, 22 = People & Blogs
        "tiktok": False,
        "tiktok_mode": "inbox",         # inbox (borrador) | direct
        "tiktok_privacy": "SELF_ONLY",
        "facebook": False,
        "instagram": False,             # Reels con el mismo token de página (cuenta IG profesional vinculada)
        "facebook_graph_version": "v24.0",
    },
    "general": {
        "notify": True,             # aviso de Windows al terminar (o fallar) un run
    },
    "storage": {
        "keep_work_days": 7,        # archivos de trabajo (tomas, audios) de runs más viejos se borran
        "cache_max_gb": 5,          # tope de la caché de clips de stock
        "delete_videos_days": 0,    # 0 = nunca borrar los videos finales
    },
    "metrics": {
        "min_age_hours": 48,
        "max_age_days": 30,
        "exploration": 0.3,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif k in out:
            out[k] = v
    return out


def load() -> dict:
    data = {}
    if SETTINGS_FILE.is_file():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    return _merge(DEFAULTS, data)


def save(new: dict) -> dict:
    merged = _merge(load(), new)
    atomic_write_text(SETTINGS_FILE, json.dumps(merged, indent=2, ensure_ascii=False))
    return merged


# ── Secretos ──────────────────────────────────────────────────────────

def get_secret(name: str) -> str | None:
    n = keyring.get_password(KEYRING_SERVICE, f"{name}#n")
    if n is None:
        return None
    parts = []
    for i in range(int(n)):
        p = keyring.get_password(KEYRING_SERVICE, f"{name}#{i}")
        if p is None:
            return None
        parts.append(p)
    return "".join(parts)


def set_secret(name: str, value: str) -> None:
    value = (value or "").strip()
    delete_secret(name)
    if not value:
        return
    chunks = [value[i:i + _CHUNK] for i in range(0, len(value), _CHUNK)]
    for i, c in enumerate(chunks):
        keyring.set_password(KEYRING_SERVICE, f"{name}#{i}", c)
    keyring.set_password(KEYRING_SERVICE, f"{name}#n", str(len(chunks)))


def delete_secret(name: str) -> None:
    n = keyring.get_password(KEYRING_SERVICE, f"{name}#n")
    count = int(n) if n else 0
    for key in [f"{name}#n"] + [f"{name}#{i}" for i in range(count)]:
        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except PasswordDeleteError:
            pass


def get_json_secret(name: str) -> dict | None:
    raw = get_secret(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json_secret(name: str, value: dict) -> None:
    set_secret(name, json.dumps(value, separators=(",", ":")))


def secrets_status() -> dict[str, bool]:
    names = list(SECRETS) + list(OAUTH_TOKENS)
    return {n: keyring.get_password(KEYRING_SERVICE, f"{n}#n") is not None for n in names}
