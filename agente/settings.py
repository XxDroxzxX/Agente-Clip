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
        "search_query": "",         # búsqueda de tendencias; vacío = el nicho traducido al idioma del video
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
        "ai_select": "smart",       # smart: IA solo donde el guion lo pide o el stock no tiene nada que encaje
                                    # hook: las primeras N tomas | all: todas (vale para ComfyUI y fal.ai)
        "comfy_max_shots": 2,       # tope de tomas IA por video (0 = sin tope)
        "comfy_chain": "scene",     # scene: encadena dentro de cada escena y corta al cambiar | all: una sola cadena
        "comfy_keyframes": True,    # cada escena arranca de una imagen clave revisada (~1 min) antes de animarla
        "comfy_director": True,     # una IA con visión revisa cada toma y regenera la que no sigue la escena
        "comfy_director_min": 6,    # nota mínima (1-10) para aceptar una toma
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
        "publish_time": "",             # «HH:MM»: los videos listos esperan hasta esa hora para publicarse (vacío = enseguida)
        "youtube": True,
        "youtube_method": "browser",    # browser (YouTube Studio con tu sesión) | api (Data API; sin auditoría queda privado)
        "youtube_privacy": "private",   # private | unlisted | public
        "youtube_category": "26",       # 26 = Howto & Style, 22 = People & Blogs
        "tiktok": False,
        "tiktok_method": "browser",     # browser (TikTok Studio con tu sesión) | api (Content Posting API)
        "browser_visible": False,       # mostrar la ventana de Chrome mientras publica (útil para revisar)
        "tiktok_mode": "inbox",         # inbox (borrador) | direct
        "tiktok_privacy": "SELF_ONLY",
        "facebook": False,
        "instagram": False,             # Reels con el mismo token de página (cuenta IG profesional vinculada)
        "facebook_graph_version": "v24.0",
        "meta_fallback": True,
        "ai_label": False,              # marcar «hecho con IA» al publicar en Instagram por navegador (decisión del usuario)          # si la API de Meta falla: Instagram por navegador y Facebook por otra vía
    },
    "general": {
        "notify": True,             # aviso de Windows al terminar (o fallar) un run
        "shutdown_after": False,    # apagar el PC al terminar la ejecución diaria (generación y publicaciones)
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


# Reglas de validación: ruta → ("int"|"float", mín, máx) o ("enum", valores). Lo inválido vuelve al valor anterior
# (o al de fábrica) y los números se ajustan al rango, para que un dato mal escrito no tumbe un run.
RULES: dict[str, tuple] = {
    "content.language": ("enum", ("es", "en", "pt")),
    "content.research_days": ("int", 3, 180),
    "llm.provider": ("enum", ("claude", "gemini", "ollama")),
    "llm.claude_effort": ("enum", ("low", "medium", "high")),
    "video.long_minutes": ("int", 1, 15),
    "video.shorts_count": ("int", 0, 5),
    "video.quality": ("enum", ("1080p", "720p")),
    "video.visual_provider": ("enum", ("pexels", "fal", "comfyui")),
    "video.fal_scope": ("enum", ("shorts", "all")),
    "video.fal_segment_seconds": ("int", 2, 10),
    "video.ai_select": ("enum", ("smart", "hook", "all")),
    "video.comfy_resolution": ("enum", ("480p", "544p", "704p")),
    "video.comfy_steps": ("int", 4, 50),
    "video.comfy_fps": ("int", 8, 30),
    "video.comfy_segment_seconds": ("int", 2, 8),
    "video.comfy_max_shots": ("int", 0, 30),
    "video.comfy_chain": ("enum", ("scene", "all")),
    "video.comfy_director_min": ("int", 1, 10),
    "video.comfy_timeout_min": ("int", 5, 120),
    "video.music_volume": ("float", 0.0, 1.0),
    "video.music_source": ("enum", ("generada", "lyria", "carpeta")),
    "video.smart_clips": ("enum", ("auto", "gemini", "claude", "off")),
    "video.review": ("enum", ("auto", "gemini", "claude", "off")),
    "video.review_min_score": ("int", 1, 10),
    "voice.engine": ("enum", ("edge", "gemini")),
    "voice.rate": ("enum", ("-10%", "+0%", "+6%", "+12%", "+20%")),
    "publish.youtube_method": ("enum", ("browser", "api")),
    "publish.youtube_privacy": ("enum", ("private", "unlisted", "public")),
    "publish.tiktok_method": ("enum", ("browser", "api")),
    "publish.tiktok_mode": ("enum", ("inbox", "direct")),
    "publish.tiktok_privacy": ("enum", ("SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE")),
    "storage.keep_work_days": ("int", 1, 365),
    "storage.cache_max_gb": ("int", 1, 200),
    "storage.delete_videos_days": ("int", 0, 3650),
    "metrics.min_age_hours": ("int", 6, 720),
    "metrics.max_age_days": ("int", 1, 365),
    "metrics.exploration": ("float", 0.0, 1.0),
}


def _get(d: dict, path: str):
    for k in path.split("."):
        d = d[k]
    return d


def _set(d: dict, path: str, v) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = v


def validate(cfg: dict, prev: dict | None = None) -> tuple[dict, list[str]]:
    """Corrige valores inválidos. Devuelve (config corregida, avisos en español para el usuario)."""
    import re
    from . import catalog
    prev = prev or DEFAULTS
    fixes: list[str] = []
    for path, rule in RULES.items():
        try:
            v = _get(cfg, path)
        except (KeyError, TypeError):
            continue
        fallback = _get(prev, path) if path.count(".") and _has(prev, path) else _get(DEFAULTS, path)
        if rule[0] == "enum":
            if v not in rule[1]:
                _set(cfg, path, fallback)
                fixes.append(f"«{v}» no es válido en {path}; se dejó «{fallback}».")
            continue
        cast = int if rule[0] == "int" else float
        try:
            n = cast(v)
        except (TypeError, ValueError):
            _set(cfg, path, fallback)
            fixes.append(f"{path} no es un número; se dejó {fallback}.")
            continue
        lo, hi = rule[1], rule[2]
        if n < lo or n > hi:
            n = min(hi, max(lo, n))
            fixes.append(f"{path} fuera de rango; se ajustó a {n}.")
        _set(cfg, path, n)
    c, v, p = cfg["content"], cfg["voice"], cfg["publish"]
    region = (c.get("region_code") or "").strip().upper()
    if region in catalog.ALPHA3:
        fixes.append(f"Región «{region}» corregida a «{catalog.ALPHA3[region]}» (YouTube usa códigos de 2 letras).")
        region = catalog.ALPHA3[region]
    if region and region not in dict(catalog.REGIONS):
        fixes.append(f"La región «{region}» no existe; se usa Global.")
        region = ""
    c["region_code"] = region
    lang = c["language"]
    if not str(v.get("name", "")).startswith(lang + "-"):
        v["name"] = catalog.DEFAULT_VOICE[lang]
        fixes.append(f"La voz no era de {catalog.LANGUAGES[lang].lower()}; se eligió {catalog.voice_label(v['name'])}.")
    if v.get("gemini_voice") not in catalog.GEMINI_VOICE_INFO:
        v["gemini_voice"] = DEFAULTS["voice"]["gemini_voice"]
    pt = str(p.get("publish_time") or "")
    if pt and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", pt):
        fixes.append(f"Hora de publicación «{pt}» inválida; se publica apenas estén listos.")
        p["publish_time"] = ""
    if not re.fullmatch(r"v\d{2}\.0", str(p.get("facebook_graph_version", ""))):
        fixes.append(f"Versión de Graph API «{p.get('facebook_graph_version')}» con formato inválido; se usa v24.0.")
        p["facebook_graph_version"] = "v24.0"
    return cfg, fixes


def _has(d: dict, path: str) -> bool:
    try:
        _get(d, path)
        return True
    except (KeyError, TypeError):
        return False


def load() -> dict:
    data = {}
    if SETTINGS_FILE.is_file():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    return _merge(DEFAULTS, data)


def save(new: dict) -> tuple[dict, list[str]]:
    """Guarda la configuración validada. Devuelve (config guardada, avisos de lo que se corrigió)."""
    prev = load()
    merged, fixes = validate(_merge(prev, new), prev)
    atomic_write_text(SETTINGS_FILE, json.dumps(merged, indent=2, ensure_ascii=False))
    return merged, fixes


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
