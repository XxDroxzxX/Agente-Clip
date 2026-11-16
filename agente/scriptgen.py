"""Generación del guion con IA (Claude API u Ollama local) en formato estructurado."""
from __future__ import annotations

import copy
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
    title: str = Field(description="Título atractivo de máximo 60 caracteres, con el término que busca la audiencia "
                                   "en las primeras palabras.")
    description: str = Field(description="Descripción para la publicación, 2-4 frases.")
    hashtags: list[str] = Field(description="3 a 6 hashtags relevantes, con #.")
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
- Retención por compuertas: 0-2 s gancho (la primera frase dice la promesa en 5-8 palabras, sin introducción ni
  saludo); 2-5 s confirmación (prueba concreta de que la promesa es real); luego el desarrollo, una idea por escena;
  cierre en bucle (la última frase conecta con la primera para que se vuelva a ver) o una sola llamada a la acción.
- La primera escena tiene como máximo 14 palabras.
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
    if research.get("top_hashtags"):
        lines.append("Hashtags más usados por los videos en tendencia del nicho (usa en cada video los 3-4 que de verdad "
                     "correspondan a su tema; no inventes otros parecidos): " + " ".join(research["top_hashtags"]))
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
    lines.append(f"SHORTS (vertical): exactamente {n}. Cada uno es independiente, de 30 a 45 segundos (≈70-100 palabras "
                 "en total; no más: la voz real es más lenta de lo que parece), con un gancho propio, una sola idea potente "
                 "y un cierre en bucle o que invite a comentar o seguir.")
    lines.append("")
    lines.append("TÍTULO Y DESCRIPCIÓN (búsqueda en YouTube y Google): el título, de máximo 60 caracteres, incluye en sus "
                 "primeras palabras el término que la audiencia escribiría para encontrar el video (sale del nicho y de los "
                 "títulos en tendencia), con lenguaje natural, sin mayúsculas sostenidas ni relleno de palabras clave. La "
                 "primera frase de la descripción (máximo 160 caracteres) repite ese término y uno secundario de forma "
                 "natural. Hashtags: 3-6 relevantes; en los Shorts incluye #shorts. Título, miniatura y gancho cuentan la "
                 "misma promesa.")
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


REACH_TAGS = {"es": ["#parati"], "en": ["#parati", "#fyp"], "pt": ["#parati", "#fyp"]}  # alcance: siempre


def finalize_hashtags(tags: list[str], niche_tags: list[str], lang: str, is_short: bool, limit: int = 8) -> list[str]:
    """Hashtags finales: los del guion y los más usados del nicho primero (son los que se muestran), luego #shorts en
    los Shorts y siempre #parati (más #fyp para audiencias en inglés o portugués). Sin repetidos."""
    out: list[str] = []

    def add(t: str):
        t = t.strip()
        if not t:
            return
        t = t if t.startswith("#") else f"#{t}"
        t = "#" + "".join(t[1:].split())
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)

    reach = REACH_TAGS.get(lang, REACH_TAGS["en"])
    fixed = (["#shorts"] if is_short else []) + reach
    room = max(0, limit - len(fixed))
    for t in tags:
        if t.lower().lstrip("#") not in {"shorts", "parati", "fyp"} and len(out) < room:
            add(t)
    for t in niche_tags:  # completa con los del nicho si el guion trajo pocos
        if len(out) >= min(room, 5):
            break
        add(t)
    for t in fixed:
        add(t)
    return out


def _gaps(pkg: "ScriptPackage", cfg: dict) -> list[str]:
    """Lo que le falta al guion respecto de lo pedido (vacío si está completo)."""
    v, out = cfg["video"], []
    n = int(v["shorts_count"])
    if len(pkg.shorts) < n:
        out.append(f"llegaron {len(pkg.shorts)} de {n} Shorts")
    if v["long_enabled"]:
        target = v["long_minutes"] * WORDS_PER_MINUTE
        words = sum(len(s.narration.split()) for s in pkg.long_video.scenes)
        if words < target * 0.5:
            out.append(f"el video largo tiene {words} palabras de unas {target:.0f}")
    return out


def generate(run: Run, cfg: dict, research: dict, hook_style: str) -> ScriptPackage:
    sid = "script"
    prompt = build_prompt(cfg, research, hook_style)
    provider = cfg["llm"]["provider"]
    label, fn = PROVIDERS.get(provider, PROVIDERS["claude"])
    run.step_progress(sid, 0.15, f"Escribiendo con {label}…", force=True)
    pkg, note = fn(cfg, prompt)
    gaps = _gaps(pkg, cfg)
    for attempt in range(2):  # a veces el modelo corta la respuesta antes de tiempo: se pide de nuevo
        if not gaps:
            break
        run.warn(f"El guion vino incompleto ({'; '.join(gaps)}); se pide de nuevo.", sid)
        retry_cfg = copy.deepcopy(cfg)
        if provider == "gemini":  # otro modelo de la cadena gratuita (el mismo suele repetir el corte)
            from . import gemini
            chain = gemini.chain(cfg["llm"].get("gemini_model"))
            retry_cfg["llm"]["gemini_model"] = chain[min(attempt + 1, len(chain) - 1)]
        try:
            reminder = ("\n\nIMPORTANTE: una respuesta anterior vino incompleta (" + "; ".join(gaps)
                        + "). Entrega el paquete completo: la cantidad exacta de Shorts y la duración pedida.")
            pkg2, note2 = fn(retry_cfg, prompt + reminder)
        except Exception as e:
            run.warn(f"El nuevo intento falló ({str(e)[:120]}).", sid)
            continue
        if len(_gaps(pkg2, cfg)) < len(gaps) or (len(pkg2.shorts) > len(pkg.shorts)):
            pkg, note = pkg2, note2
            gaps = _gaps(pkg, cfg)
    if gaps:
        run.warn(f"El guion sigue incompleto ({'; '.join(gaps)}); se continúa con lo que hay.", sid)
    if int(cfg["video"]["shorts_count"]) > 0 and not pkg.shorts:
        raise RuntimeError("La IA no escribió ningún Short. Vuelve a intentar el run; si se repite, prueba otro modelo.")

    # limpieza mínima y validación
    n = int(cfg["video"]["shorts_count"])
    pkg.shorts = pkg.shorts[:n]
    for plan in [pkg.long_video, *pkg.shorts]:
        plan.scenes = [s for s in plan.scenes if s.narration.strip()]
        plan.hashtags = finalize_hashtags(plan.hashtags, research.get("top_hashtags", []),
                                          cfg["content"]["language"], is_short=plan is not pkg.long_video)
        if not plan.scenes:
            raise RuntimeError(f"El guion «{plan.title}» no tiene escenas.")
    run.info(f"Guion listo: «{pkg.topic}» ({note})", sid)
    run.path("script.json").write_text(json.dumps(pkg.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    return pkg
