"""Revisión de calidad con IA antes de publicar.

Toma cuadros del video final y (con Gemini) también escucha el audio: revisa que las imágenes
correspondan a lo que se narra y al tema del canal, que los textos no se corten ni se tapen,
que la voz se entienda sobre la música y que lo dicho coincida con el guion.
Gemini (gratis) revisa imagen + audio; Claude (de pago) solo imagen.
"""
from __future__ import annotations

import base64
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from . import ffmpeg
from . import settings as S

N_FRAMES = 10


class Issue(BaseModel):
    severity: Literal["alta", "media", "baja"] = Field(description="alta = no se debería publicar así.")
    at: str = Field(description="Momento aproximado (ej. '0:12') o 'general'.")
    problem: str = Field(description="Qué está mal, en una frase concreta.")


class Review(BaseModel):
    score: int = Field(description="Calidad general de 1 a 10 para publicar en redes.")
    issues: list[Issue] = Field(default_factory=list)
    summary: str = Field(description="Una o dos frases con la conclusión.")


PROMPT = """Eres un editor exigente que revisa videos antes de publicarlos en {platform} para un canal sobre «{niche}».
Recibes {n} cuadros del video final, en orden, cada uno con su segundo{audio_note}.
Título: «{title}»
Guion narrado:
{script}

Revisa y reporta solo problemas reales y concretos:
- Imágenes sin relación con lo que se narra en ese momento, o que contradicen el tema del canal (p. ej. carne en un canal vegano).
- Textos o gráficos cortados por el borde, superpuestos entre sí o ilegibles; subtítulos que tapan algo importante.
- Cuadros negros, congelados o de muy baja calidad.{audio_checks}
Severidad «alta» solo si un espectador lo notaría claramente y daña el video. Si está bien, devuelve la lista vacía.
Responde solo con el JSON pedido."""

AUDIO_CHECKS = """
- Audio: la voz se entiende con claridad; la música no la tapa ni distrae; los efectos no molestan;
  lo que dice la voz coincide con el guion (palabras mal pronunciadas, cortes o silencios raros); el final no se corta."""


def provider(cfg: dict) -> str | None:
    mode = cfg["video"].get("review", "auto")
    if mode == "off":
        return None
    has_gem = bool(S.get_secret("gemini_api_key"))
    has_cl = bool(S.get_secret("anthropic_api_key"))
    if mode == "gemini":
        return "gemini" if has_gem else None
    if mode == "claude":
        return "claude" if has_cl else None
    return "gemini" if has_gem else "claude" if has_cl else None


def _frames(video: Path, duration: float, d: Path) -> list[tuple[float, Path]]:
    out = []
    for i in range(N_FRAMES):
        t = duration * (i + 0.5) / N_FRAMES
        out.append((t, ffmpeg.extract_frame(video, d / f"f{i:02d}.jpg", at=t, width=360)))
    return out


def review_video(cfg: dict, video: Path, plan, duration: float, portrait: bool,
                 log: Callable[[str, str], None]) -> dict | None:
    prov = provider(cfg)
    if not prov:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="review_"))
    try:
        frames = _frames(video, duration, tmp)
        script = "\n".join(f"- {sc.narration}" for sc in plan.scenes)
        with_audio = prov == "gemini"
        system = PROMPT.format(
            platform="Shorts/TikTok/Reels (vertical)" if portrait else "YouTube (horizontal)",
            niche=cfg["content"]["niche"], n=len(frames), title=plan.title, script=script,
            audio_note=" y el audio completo del video" if with_audio else "",
            audio_checks=AUDIO_CHECKS if with_audio else "")
        if prov == "gemini":
            from . import gemini
            inp: list = []
            for t, f in frames:
                inp += [{"type": "text", "text": f"Cuadro en el segundo {t:.0f}"},
                        {"type": "image", "data": base64.b64encode(f.read_bytes()).decode(), "mime_type": "image/jpeg"}]
            mp3 = tmp / "audio.mp3"
            ffmpeg.run(["-i", video, "-vn", "-ac", 1, "-ar", 22050, "-b:a", "48k", mp3])
            inp += [{"type": "text", "text": "Audio completo del video:"},
                    {"type": "audio", "data": base64.b64encode(mp3.read_bytes()).decode(), "mime_type": "audio/mp3"}]
            text, model = gemini.generate(gemini.chain(None, gemini.FREE_MODELS), inp, system=system,
                                          schema=Review.model_json_schema(), thinking="low", timeout=300,
                                          log=lambda m: log(m, "info"))
            rev = Review.model_validate_json(text)
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=S.get_secret("anthropic_api_key"), max_retries=2)
            content: list = []
            for t, f in frames:
                content += [{"type": "text", "text": f"Cuadro en el segundo {t:.0f}"},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(f.read_bytes()).decode()}}]
            resp = client.messages.parse(model="claude-haiku-5-5", max_tokens=2000, system=system,
                                         messages=[{"role": "user", "content": content}], output_format=Review)
            if resp.parsed_output is None:
                raise RuntimeError("Claude no devolvió una revisión válida.")
            rev, model = resp.parsed_output, "claude-haiku-5-5"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    high = [i for i in rev.issues if i.severity == "alta"]
    min_score = int(cfg["video"].get("review_min_score", 6))
    return {
        "ok": not high and rev.score >= min_score,
        "score": rev.score,
        "summary": rev.summary,
        "issues": [i.model_dump() for i in rev.issues],
        "model": model,
        "audio": with_audio,
    }
