"""Selección inteligente de clips: una IA con visión mira las miniaturas de los
candidatos de stock y los ordena según lo que dice la narración de cada escena.

Proveedores: Gemini (gratis) o Claude (de pago, modelo Haiku). Si ninguno está
disponible o falla, se usa el orden de relevancia del banco de clips.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, ValidationError

from . import settings as S

MAX_IMAGES_PER_CALL = 24
CLAUDE_VISION_MODEL = "claude-haiku-5-5"

PROMPT = """Eres editor de video para redes sociales de un canal sobre «{niche}». Para cada escena verás la
narración y clips candidatos (una miniatura de cada uno). Ordena los candidatos de cada escena del MÁS al MENOS adecuado.
Criterios, en este orden:
1. Que muestre de forma concreta lo que dice la narración (no solo algo del mismo tema).
2. Calidad visual: nítido, bien iluminado, atractivo.
3. Sin texto incrustado, marcas de agua ni logos visibles.
4. Que funcione en formato {orient}.
EXCLUYE del ranking (no los pongas) los candidatos sin relación con la escena, los abstractos o de relleno
(manchas de color, paisajes sin relación, instrumentos musicales, etc.) y los que contradigan el tema del canal
(p. ej. carne, pescado o huevos en un canal vegano). Si ninguno sirve, devuelve un ranking vacío para esa escena.
Responde solo con el JSON pedido. Los números de candidato son los que aparecen antes de cada imagen."""


class SceneRank(BaseModel):
    scene: int
    ranking: list[int]


class Ranking(BaseModel):
    scenes: list[SceneRank]


def provider(cfg: dict) -> str | None:
    mode = cfg["video"].get("smart_clips", "auto")
    has_gem = bool(S.get_secret("gemini_api_key"))
    has_cl = bool(S.get_secret("anthropic_api_key"))
    if mode == "off":
        return None
    if mode == "gemini":
        return "gemini" if has_gem else None
    if mode == "claude":
        return "claude" if has_cl else None
    return "gemini" if has_gem else "claude" if has_cl else None  # auto: primero la opción gratuita


def _call(prov: str, cfg: dict, system: str, parts: list, model: type[BaseModel], log, max_tokens: int = 2000):
    """Envía texto e imágenes (Path) al proveedor con visión y valida la respuesta con `model`."""
    if prov == "gemini":
        from . import gemini
        inp = [{"type": "text", "text": p} if isinstance(p, str)
               else {"type": "image", "data": base64.b64encode(p.read_bytes()).decode(), "mime_type": "image/jpeg"}
               for p in parts]
        chain_model = cfg["video"].get("vision_gemini_model") or None
        text, _ = gemini.generate(gemini.chain(chain_model, gemini.LITE_FIRST), inp, system=system,
                                  schema=model.model_json_schema(), thinking="low", timeout=180,
                                  log=lambda m: log(m, "info"), max_tokens=max_tokens)
        return model.model_validate_json(text)
    import anthropic
    client = anthropic.Anthropic(api_key=S.get_secret("anthropic_api_key"), max_retries=2)
    content = [{"type": "text", "text": p} if isinstance(p, str)
               else {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(p.read_bytes()).decode()}}
               for p in parts]
    resp = client.messages.parse(model=CLAUDE_VISION_MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": content}], output_format=model)
    if resp.parsed_output is None:
        raise RuntimeError("Claude no devolvió una respuesta válida.")
    return resp.parsed_output


def _ask(prov: str, cfg: dict, parts: list, orient: str, log) -> Ranking:
    return _call(prov, cfg, PROMPT.format(orient=orient, niche=cfg["content"]["niche"]), parts, Ranking, log)


# ── director de video IA ──────────────────────────────

DIRECTOR_PROMPT = """Eres director de un video generado con IA para un canal sobre «{niche}». Verás dos cuadros
(mitad y final) de una toma recién generada, la narración que la acompaña y el prompt que se usó.
Juzga si la toma muestra de forma reconocible lo que pide la escena: el sujeto principal debe verse y la acción o
ambiente deben corresponder. No castigues el estilo artístico ni la oscuridad si el tema lo pide. Castiga: sujeto
ausente o irreconocible, cuerpos deformes, objetos sin sentido, texto o marcas de agua, imagen degradada.
score: 1 (nada que ver o roto) a 10 (perfecta). Si score < 6, escribe en better_prompt un prompt NUEVO en inglés
(1-2 frases) que nombre explícitamente el sujeto principal, su aspecto, la acción, el lugar y la cámara, sin
negaciones. issue: el problema en pocas palabras, en español."""


class Verdict(BaseModel):
    score: int
    issue: str = Field("", max_length=200)
    better_prompt: str = Field("", max_length=600)


def judge_shot(cfg: dict, frames: list[Path], narration: str, prompt: str, log) -> Verdict | None:
    """Revisa una toma IA. Devuelve None si no hay proveedor con visión o la consulta falla (no bloquea el run)."""
    prov = provider(cfg)
    if not prov:
        return None
    parts: list = [f"NARRACIÓN: «{narration}»", f"PROMPT USADO: {prompt}"]
    for n, f in enumerate(frames):
        parts += [f"Cuadro {n + 1}", f]
    try:
        return _call(prov, cfg, DIRECTOR_PROMPT.format(niche=cfg["content"]["niche"]), parts, Verdict, log, 800)
    except ValidationError as e:
        # respuesta cortada (p. ej. el modelo se repite sin fin): basta con la nota para decidir
        m = re.search(r'"score"\s*:\s*(\d+)', str(e))
        if m:
            return Verdict(score=int(m.group(1)), issue="respuesta del director incompleta")
        log("Director IA no disponible para esta toma (respuesta inválida); se acepta tal cual.", "warn")
        return None
    except Exception as e:
        log(f"Director IA no disponible para esta toma ({e}); se acepta tal cual.", "warn")
        return None


def rank_scenes(cfg: dict, scenes: list[dict], portrait: bool,
                log: Callable[[str, str], None]) -> dict[int, list[int]]:
    """scenes: [{"scene": i, "narration": str, "query": str, "thumbs": [Path|None, ...]}]
    Devuelve {scene: [índices de candidatos en orden de preferencia]} (puede faltar alguna escena)."""
    prov = provider(cfg)
    if not prov:
        return {}
    orient = "vertical 9:16" if portrait else "horizontal 16:9"
    out: dict[int, list[int]] = {}
    batch: list[dict] = []
    count = 0

    def flush():
        nonlocal batch, count
        if not batch:
            return
        parts: list = []
        for sc in batch:
            parts.append(f"ESCENA {sc['scene']}: «{sc['narration']}» (búsqueda usada: {sc['query']})")
            for j, t in enumerate(sc["thumbs"]):
                if t is not None:
                    parts += [f"Escena {sc['scene']} · candidato {j}", t]
        try:
            res = _ask(prov, cfg, parts, orient, log)
            for r in res.scenes:
                valid = [j for j in r.ranking if isinstance(j, int)]
                out[r.scene] = list(dict.fromkeys(valid))
        except Exception as e:
            log(f"Selección inteligente no disponible en este lote ({e}); se usa el orden del banco.", "warn")
        batch, count = [], 0

    for sc in scenes:
        n = sum(1 for t in sc["thumbs"] if t is not None)
        if n < 1:
            continue  # un candidato único también se revisa: puede no tener relación
        if count + n > MAX_IMAGES_PER_CALL:
            flush()
        batch.append(sc)
        count += n
    flush()
    if out:
        log(f"Clips elegidos con visión ({'Gemini' if prov == 'gemini' else 'Claude'}) para {len(out)} escenas.", "info")
    return out


def rank_pool(cfg: dict, scenes: list[dict], pool: list, portrait: bool,
              log: Callable[[str, str], None]) -> dict[int, list[int]]:
    """Segunda vuelta: varias escenas eligen de un mismo grupo de clips genéricos del nicho.
    scenes: [{"scene": i, "narration": str}]; pool: [Path|None]. Devuelve {scene: [índices del pool]}."""
    prov = provider(cfg)
    if not prov or not scenes or not any(pool):
        return {}
    parts: list = [f"ESCENA {sc['scene']}: «{sc['narration']}»" for sc in scenes]
    parts.append("Candidatos compartidos por todas las escenas (cada uno se usará en una sola escena):")
    for j, t in enumerate(pool[:MAX_IMAGES_PER_CALL]):
        if t is not None:
            parts += [f"Candidato {j}", t]
    try:
        res = _ask(prov, cfg, parts, "vertical 9:16" if portrait else "horizontal 16:9", log)
    except Exception as e:
        log(f"Segunda selección de clips no disponible ({e}).", "warn")
        return {}
    return {r.scene: list(dict.fromkeys(j for j in r.ranking if isinstance(j, int))) for r in res.scenes}

