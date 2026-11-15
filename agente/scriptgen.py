"""Generación del guion con IA (Claude API u Ollama local) en formato estructurado."""
from __future__ import annotations

import json

import requests
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import settings as S
from .events import Run
from .learning import HOOK_STYLES, insights, top_own_titles

WORDS_PER_MINUTE = 150  # narración en español a ritmo dinámico


class Animation(BaseModel):
    type: Literal["titulo", "lista", "dato", "frase", "cta"] = Field(
        description="titulo: gancho en texto grande; lista: enumeración; dato: cifra destacada; "
                    "frase: idea clave en tarjeta; cta: llamada a seguir/comentar al final.")
    headline: str = Field(default="", description="Texto principal, MUY corto (2-7 palabras). En lista: título breve (ej. '3 trucos'). En cta: la invitación.")
    highlight: str = Field(default="", description="Una palabra de headline que se resalta en color (opcional).")
    items: list[str] = Field(default_factory=list, description="Solo para lista: 2-4 elementos de 1-4 palabras.")
    value: str = Field(default="", description="Solo para dato: la cifra con su unidad, ej. '73%', '3x', '15 min'.")
    label: str = Field(default="", description="En dato: qué significa la cifra (2-5 palabras). En cta: texto del botón (1-2 palabras, ej. 'Sígueme').")


class Scene(BaseModel):
    narration: str = Field(description="Texto exacto que dirá la voz en off. Sin títulos, emojis ni acotaciones.")
    visual_query: str = Field(description="2 a 4 palabras EN INGLÉS, concretas y filmables, para buscar video de stock (ej. 'chopping fresh vegetables').")
    visual_prompt: str = Field(description="Prompt EN INGLÉS de 1-2 frases para un generador de video IA. Nombra SIEMPRE el sujeto "
                               "principal con las mismas palabras de visual_bible (no uses 'it' ni 'the same'), su acción concreta, el lugar, "
                               "la cámara y la luz. Una sola acción simple y filmable en 5 segundos.")
    animation: Optional[Animation] = Field(default=None, description="Gráfico animado sobre la toma (opcional). null si la escena no lo necesita.")
    needs_ai: bool = Field(default=False, description="true si la escena NO se puede mostrar bien con video de stock: aparece el "
                           "personaje de la historia, una acción o momento concreto de la trama, algo fantástico o inexistente. "
                           "false si es genérica y fácil de encontrar en un banco de videos (paisaje, ciudad, comida, objetos, "
                           "gente anónima). Marca solo las escenas que de verdad lo necesitan.")


class MusicBrief(BaseModel):
    mood: Literal["energetico", "alegre", "inspirador", "tranquilo", "misterioso", "emotivo", "tecnologico"] = Field(
        description="Estado de ánimo de la música de fondo que mejor acompaña el tono de este video.")
    prompt: str = Field(description="EN INGLÉS, 1 frase para un generador de música IA: género, instrumentos, energía y tempo "
                                    "(ej. 'upbeat lo-fi hip hop with warm piano and soft drums, 85 bpm').")


class VideoPlan(BaseModel):
    title: str = Field(description="Título atractivo, máximo 90 caracteres.")
    description: str = Field(description="Descripción para la publicación, 2-4 frases.")
    hashtags: list[str] = Field(description="5 a 8 hashtags relevantes, con #.")
    visual_bible: str = Field(default="", description="EN INGLÉS, 2-3 frases que fijan el aspecto del video para el generador IA: "
                              "sujeto o personaje principal (especie/edad, rasgos, ropa, colores), lugar y época, estilo visual y paleta. "
                              "Se agrega a cada toma para que el personaje y el ambiente no cambien.")
    scenes: list[Scene]
    thumbnail_text: str = Field(default="", description="Texto para la miniatura: 2 a 5 palabras impactantes, "
                                                        "distintas del título (ej. 'ADIÓS AL HUEVO').")
    music: Optional[MusicBrief] = Field(default=None, description="Música de fondo acorde al video.")


class ScriptPackage(BaseModel):
    topic: str = Field(description="Tema concreto y original elegido para hoy.")
    angle: str = Field(description="Por qué este enfoque debería funcionar, en una frase.")
    long_video: VideoPlan
    shorts: list[VideoPlan]
    broll_queries: list[str] = Field(default_factory=list, description=(
        "3 a 5 búsquedas EN INGLÉS de video de stock genéricas que SIEMPRE encajan con el nicho y lo respetan "
        "(ej. cocina vegana: 'chopping vegetables', 'plant based bowl'). Se usan cuando no hay clip para una escena."))


SYSTEM = """Eres un guionista experto en contenido de video corto y largo para YouTube, TikTok y Facebook.
Escribes narraciones naturales para voz en off: frases cortas, ritmo ágil, lenguaje hablado.
Reglas:
- La narración es SOLO lo que se dice en voz alta: sin encabezados, sin "Escena 1", sin emojis, sin indicaciones de cámara, sin markdown.
- La primera escena debe enganchar en los primeros 2 segundos.
- Cada escena dura entre 5 y 12 segundos de narración (≈12-30 palabras).
- Los visual_query describen cosas que existen en bancos de video (personas, objetos, lugares, acciones), en inglés,
  y nunca contradicen el nicho (p. ej. en cocina vegana: nada de carne, pescado, huevos ni lácteos animales).
- El contenido debe ser original: inspírate en las tendencias, nunca copies títulos ni guiones.
- No inventes datos falsos; si das cifras, que sean conocidas y verificables."""


def build_prompt(cfg: dict, research: dict, hook_style: str) -> str:
    c, v = cfg["content"], cfg["video"]
    lines = [f"Nicho: {c['niche']}", f"Idioma de la narración: {c['language']}", f"Audiencia: {c['audience']}", ""]
    vids = research.get("videos", [])[:10]
    if vids:
        lines.append("Videos en tendencia del nicho (últimos días), ordenados por rendimiento:")
        for x in vids:
            lines.append(f"- «{x['title']}» — {x['views_per_day']:.0f} vistas/día, engagement {x['engagement']*100:.1f}%, duración {x['duration_s']}s")
        lines.append("")
    own = top_own_titles()
    if own:
        lines.append("Nuestros títulos que mejor han funcionado (aprende del estilo, no repitas el tema):")
        lines += [f"- {t}" for t in own]
        lines.append("")
    learned = insights()
    if learned:
        lines.append("Lo que han mostrado las métricas de nuestras publicaciones (tenlo en cuenta, sin volverlo una regla rígida):")
        lines += [f"- {x}" for x in learned]
        lines.append("")
    lines.append(f"Estilo de gancho obligatorio para hoy: {hook_style} — {HOOK_STYLES[hook_style]}")
    lines.append("")
    if v["long_enabled"]:
        words = int(v["long_minutes"] * WORDS_PER_MINUTE)
        lines.append(f"VIDEO LARGO (horizontal): unos {v['long_minutes']} minutos ≈ {words} palabras de narración en total, "
                     f"con introducción-gancho, 3-5 bloques de valor con ejemplos concretos, llamada a la acción breve y cierre.")
    else:
        lines.append("VIDEO LARGO: no se necesita; devuelve long_video con una sola escena breve.")
    n = int(v["shorts_count"])
    lines.append(f"SHORTS (vertical): exactamente {n}. Cada uno es independiente, de 30 a 50 segundos (≈80-120 palabras), "
                 "con un gancho propio, una sola idea potente y un cierre que invite a comentar o seguir.")
    lines.append("")
    lines.append("MINIATURA: en cada video, `thumbnail_text` con 2-5 palabras que despierten curiosidad (no repitas el título).")
    lines.append("RESPALDO VISUAL: en `broll_queries` 3-5 búsquedas genéricas de stock en inglés que siempre encajen con el nicho.")
    if v.get("music", True):
        lines.append("MÚSICA: en cada video indica `music` con el estado de ánimo que acompañe su tono "
                     "(no siempre el mismo: varía según el tema y el gancho).")
    if v.get("animations", True):
        lines.append("ANIMACIONES: agrega `animation` en 1 de cada 3 o 4 escenas, donde refuerce el mensaje: "
                     "la primera escena de cada video (titulo con el gancho), enumeraciones (lista), cifras reales (dato), "
                     "una idea memorable (frase) y la última escena (cta). Textos muy cortos, en el idioma del video, "
                     "que resuman la narración sin copiarla entera. El resto de escenas: animation = null.")
    else:
        lines.append("ANIMACIONES: desactivadas; deja animation = null en todas las escenas.")
    if c.get("extra_instructions"):
        lines += ["", f"Instrucciones adicionales: {c['extra_instructions']}"]
    return "\n".join(lines)


def _claude(cfg: dict, prompt: str) -> tuple[ScriptPackage, str]:
    import anthropic

    key = S.get_secret("anthropic_api_key")
    if not key:
        raise RuntimeError("Falta la Claude API key (Configuración → Credenciales).")
    client = anthropic.Anthropic(api_key=key, max_retries=3)
    model = cfg["llm"]["claude_model"]
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=ScriptPackage,
        output_config={"effort": cfg["llm"].get("claude_effort", "medium")},
    )
    if model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"):
        # Si el modelo rechaza la solicitud por un falso positivo, el servidor reintenta con otro modelo.
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        resp = client.beta.messages.parse(**kwargs)
    except anthropic.AuthenticationError:
        raise RuntimeError("La Claude API key no es válida.")
    except anthropic.PermissionDeniedError:
        raise RuntimeError("La Claude API key no tiene permisos para este modelo.")
    except anthropic.RateLimitError:
        raise RuntimeError("Límite de uso de la API de Claude alcanzado; inténtalo más tarde.")
    except anthropic.APIConnectionError:
        raise RuntimeError("No hay conexión con la API de Claude.")
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude rechazó generar el guion; ajusta el nicho o las instrucciones.")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError("La respuesta de Claude quedó incompleta; reduce la duración del video largo.")
    u = resp.usage
    cost_note = f"tokens entrada {u.input_tokens}, salida {u.output_tokens}"
    return resp.parsed_output, cost_note


def _ollama(cfg: dict, prompt: str) -> tuple[ScriptPackage, str]:
    url = cfg["llm"]["ollama_url"].rstrip("/") + "/api/chat"
    body = {
        "model": cfg["llm"]["ollama_model"],
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "format": ScriptPackage.model_json_schema(),
        "stream": False,
        "options": {"temperature": 0.7, "num_ctx": 8192},
    }
    try:
        r = requests.post(url, json=body, timeout=1800)
    except requests.ConnectionError:
        raise RuntimeError("Ollama no está en ejecución. Instálalo desde ollama.com y ábrelo, "
                           "o cambia a Claude en Configuración.")
    if r.status_code == 404:
        m = cfg["llm"]["ollama_model"]
        raise RuntimeError(f"El modelo «{m}» no está descargado en Ollama. Ejecuta en una terminal: ollama pull {m}")
    r.raise_for_status()
    content = r.json()["message"]["content"]
    return ScriptPackage.model_validate_json(content), "Ollama local"


def _gemini(cfg: dict, prompt: str) -> tuple[ScriptPackage, str]:
    from . import gemini
    models = gemini.chain(cfg["llm"].get("gemini_model"))
    try:
        text, used = gemini.generate(models, prompt, system=SYSTEM, schema=ScriptPackage.model_json_schema(),
                                     thinking="high")
    except gemini.GeminiError as e:
        raise RuntimeError(str(e))
    try:
        return ScriptPackage.model_validate_json(text), f"Gemini {used} (plan gratuito)"
    except ValueError as e:
        raise RuntimeError(f"Gemini devolvió un guion con formato inválido; vuelve a intentarlo. ({str(e)[:150]})")


PROVIDERS = {"claude": ("Claude", _claude), "ollama": ("Ollama", _ollama), "gemini": ("Gemini", _gemini)}


def generate(run: Run, cfg: dict, research: dict, hook_style: str) -> ScriptPackage:
    sid = "script"
    prompt = build_prompt(cfg, research, hook_style)
    provider = cfg["llm"]["provider"]
    label, fn = PROVIDERS.get(provider, PROVIDERS["claude"])
    run.step_progress(sid, 0.15, f"Escribiendo con {label}…", force=True)
    pkg, note = fn(cfg, prompt)

    # limpieza mínima y validación
    n = int(cfg["video"]["shorts_count"])
    pkg.shorts = pkg.shorts[:n]
    for plan in [pkg.long_video, *pkg.shorts]:
        plan.scenes = [s for s in plan.scenes if s.narration.strip()]
        plan.hashtags = [h if h.startswith("#") else f"#{h}" for h in plan.hashtags][:8]
        if not plan.scenes:
            raise RuntimeError(f"El guion «{plan.title}» no tiene escenas.")
    run.info(f"Guion listo: «{pkg.topic}» ({note})", sid)
    run.path("script.json").write_text(json.dumps(pkg.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    return pkg
