"""Selección inteligente de clips: una IA con visión mira las miniaturas de los
candidatos de stock y los ordena según lo que dice la narración de cada escena.

Proveedores: Gemini (gratis) o Claude (de pago, modelo Haiku). Si ninguno está
disponible o falla, se usa el orden de relevancia del banco de clips.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from . import settings as S

MAX_IMAGES_PER_CALL = 24
CLAUDE_VISION_MODEL = "claude-haiku-5-5"

PROMPT = """Eres editor de video para redes sociales. Para cada escena verás la narración y varios clips
candidatos (una miniatura de cada uno). Ordena los candidatos de cada escena del MÁS al MENOS adecuado.
Criterios, en este orden:
1. Que muestre de forma concreta lo que dice la narración (no solo algo del mismo tema).
2. Calidad visual: nítido, bien iluminado, atractivo.
3. Sin texto incrustado, marcas de agua ni logos visibles.
4. Que funcione en formato {orient}.
Excluye del ranking los candidatos que no tienen relación con la escena.
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


def _ask(prov: str, cfg: dict, parts: list, orient: str, log) -> Ranking:
    system = PROMPT.format(orient=orient)
    if prov == "gemini":
        from . import gemini
        inp = [{"type": "text", "text": p} if isinstance(p, str)
               else {"type": "image", "data": base64.b64encode(p.read_bytes()).decode(), "mime_type": "image/jpeg"}
               for p in parts]
        model = cfg["video"].get("vision_gemini_model") or None
        text, _ = gemini.generate(gemini.chain(model, gemini.LITE_FIRST), inp, system=system,
                                  schema=Ranking.model_json_schema(), thinking="low", timeout=180,
                                  log=lambda m: log(m, "info"))
        return Ranking.model_validate_json(text)
    import anthropic
    client = anthropic.Anthropic(api_key=S.get_secret("anthropic_api_key"), max_retries=2)
    content = [{"type": "text", "text": p} if isinstance(p, str)
               else {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(p.read_bytes()).decode()}}
               for p in parts]
    resp = client.messages.parse(model=CLAUDE_VISION_MODEL, max_tokens=2000, system=system,
                                 messages=[{"role": "user", "content": content}], output_format=Ranking)
    if resp.parsed_output is None:
        raise RuntimeError("Claude no devolvió un ranking válido.")
    return resp.parsed_output


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
        if n < 2:
            continue  # nada que elegir
        if count + n > MAX_IMAGES_PER_CALL:
            flush()
        batch.append(sc)
        count += n
    flush()
    if out:
        log(f"Clips elegidos con visión ({'Gemini' if prov == 'gemini' else 'Claude'}) para {len(out)} escenas.", "info")
    return out

