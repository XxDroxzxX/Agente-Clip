"""Narración con voz neuronal y tiempos por palabra (subtítulos y animaciones).

Motores:
- edge: voces de Microsoft Edge (gratis, sin clave). Entrega el tiempo exacto de cada palabra.
- gemini: Gemini TTS (gratis con la Gemini API key, voz más expresiva). No entrega tiempos por
  palabra: se estiman alineando el texto con las pausas reales del audio (ver `align_words`).
"""
from __future__ import annotations

import asyncio
import re
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import edge_tts
import numpy as np

from . import ffmpeg

SAMPLE_RATE = 44100
SCENE_GAP = 0.25  # silencio entre escenas (s)

GEMINI_TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
# Voces predefinidas de Gemini TTS (hablan español; el acento lo da el texto)
GEMINI_VOICES = ["Puck", "Kore", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr", "Enceladus",
                 "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Achird", "Sadachbia", "Sulafat"]


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class SceneAudio:
    wav: Path
    duration: float           # incluye el silencio final
    words: list[Word] = field(default_factory=list)  # tiempos relativos a la escena


class TTSError(RuntimeError):
    pass


# ── edge-tts ───────────────────────────────────────────

async def _speak(text: str, voice: str, rate: str, mp3: Path) -> list[Word]:
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words: list[Word] = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append(Word(chunk["text"], start, start + chunk["duration"] / 1e7))
    return words


def _edge(text: str, voice: str, rate: str, mp3: Path) -> list[Word]:
    last_err = None
    for _ in range(3):
        try:
            words = asyncio.run(_speak(text, voice, rate, mp3))
            # el servicio a veces responde sin audio (o sin palabras): eso daría un video mudo
            if mp3.stat().st_size < 2000 or (not words and any(c.isalpha() for c in text)):
                raise RuntimeError("el servicio de voz devolvió un audio vacío")
            return words
        except Exception as e:  # red inestable o respuesta vacía: reintenta
            last_err = e
    raise TTSError(str(last_err))


# ── Gemini TTS ─────────────────────────────────────────

def _gemini(text: str, voice: str, style: str, raw: Path) -> None:
    from . import gemini

    body = {
        "input": [{"type": "user_input", "content": [{
            "type": "text", "text": text,
            "annotations": [{"type": "speech_metadata", "style": style}] if style else []}]}],
        "response_format": {"type": "audio", "mime_type": "audio/wav"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    last = None
    for attempt in range(4):  # el plan gratuito tiene pocas solicitudes por minuto
        try:
            data, _ = gemini.interact(GEMINI_TTS_MODELS, body, timeout=180)
            audio = gemini.output_audio(data)
            if not audio or len(audio) < 4000:
                raise TTSError("Gemini devolvió un audio vacío")
            raw.write_bytes(audio)
            return
        except gemini.GeminiError as e:
            last = e
            if "no es válida" in str(e) or "conexión" in str(e):
                break
            time.sleep(20 * (attempt + 1))
        except TTSError as e:
            last = e
    raise TTSError(f"Gemini TTS: {last}")


_PUNCT = "\"'«»“”()[]"
_TRAIL = _PUNCT + ".,;:…"  # se quita de las palabras (Edge tampoco la incluye); ¿? y ¡! se conservan


def _tokens(text: str) -> list[str]:
    return [t for t in (w.strip(_TRAIL) for w in text.split()) if any(c.isalnum() for c in t)]


def speech_segments(samples: np.ndarray, sr: int, min_pause: float = 0.16) -> list[tuple[float, float]]:
    """Tramos con voz (inicio, fin) en segundos, separados por pausas de al menos `min_pause`."""
    hop = int(sr * 0.01)
    n = len(samples) // hop
    if n == 0:
        return []
    frames = samples[: n * hop].astype(np.float32).reshape(n, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms / (np.abs(samples).max() + 1e-9))
    voiced = db > max(-38.0, np.percentile(db, 95) - 30)
    segs, start, silence = [], None, 0
    gap = int(min_pause / 0.01)
    for i, v in enumerate(voiced):
        if v:
            if start is None:
                start = i
            silence = 0
        elif start is not None:
            silence += 1
            if silence >= gap:
                segs.append((start, i - silence + 1))
                start, silence = None, 0
    if start is not None:
        segs.append((start, n - silence))
    return [(a * 0.01, b * 0.01) for a, b in segs if b - a >= 3]


def _weight(tok: str) -> float:
    letters = sum(c.isalnum() for c in tok)
    return max(2.0, letters + 1.5)


def align_words(text: str, samples: np.ndarray, sr: int) -> list[Word]:
    """Estima el tiempo de cada palabra: reparte las frases (cortadas en la puntuación) entre los tramos
    con voz y, dentro de cada tramo, las palabras según su largo. Preciso a ~0,1-0,2 s."""
    toks = _tokens(text)
    segs = speech_segments(samples, sr)
    if not toks:
        return []
    if not segs:
        dur = len(samples) / sr
        segs = [(0.0, dur)]
    # frases según la puntuación del texto original
    phrases: list[list[str]] = [[]]
    for raw in text.split():
        t = raw.strip(_TRAIL)
        if any(c.isalnum() for c in t):
            phrases[-1].append(t)
        if re.search(r"[,.;:!?…]$", raw.rstrip(_PUNCT)) and phrases[-1]:
            phrases.append([])
    phrases = [p for p in phrases if p]

    def spread(words: list[str], a: float, b: float) -> list[Word]:
        ws = [_weight(w) for w in words]
        tot = sum(ws)
        out, t = [], a
        for w, x in zip(words, ws):
            d = (b - a) * x / tot
            out.append(Word(w, round(t, 3), round(t + d, 3)))
            t += d
        return out

    if len(phrases) == len(segs):  # cada pausa real coincide con una pausa del texto
        out = []
        for p, (a, b) in zip(phrases, segs):
            out += spread(p, a, b)
        return out
    # si no coinciden: se reparte todo el texto sobre el tiempo con voz, saltando las pausas
    total_voiced = sum(b - a for a, b in segs)
    ws = [_weight(w) for w in toks]
    tot = sum(ws)
    out, acc = [], 0.0

    def to_real(x: float) -> float:
        for a, b in segs:
            if x <= b - a:
                return a + x
            x -= b - a
        return segs[-1][1]

    for w, x in zip(toks, ws):
        d = total_voiced * x / tot
        out.append(Word(w, round(to_real(acc + 1e-4), 3), round(to_real(acc + d), 3)))
        acc += d
    return out


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, sr


# ── API pública ────────────────────────────────────────

def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def synthesize_scene(text: str, voice_cfg: dict, out_dir: Path, idx: int, gap: float = SCENE_GAP,
                     engine: str | None = None, lang: str = "es") -> SceneAudio:
    """voice_cfg: sección «voice» de la configuración. engine fuerza «edge» o «gemini»."""
    engine = engine or voice_cfg.get("engine", "edge")
    wav = out_dir / f"scene_{idx:02d}.wav"
    try:
        if engine == "gemini":
            raw = out_dir / f"scene_{idx:02d}.gem.wav"
            from .catalog import reading_instruction
            _gemini(text, voice_cfg.get("gemini_voice", "Puck"),
                    reading_instruction(voice_cfg.get("gemini_style", ""), lang), raw)
            # sin silencios al inicio/final, para que los tiempos estimados arranquen en la voz
            clean = out_dir / f"scene_{idx:02d}.clean.wav"
            ffmpeg.run(["-i", raw, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                        "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                        "-ar", SAMPLE_RATE, "-ac", 1, "-c:a", "pcm_s16le", clean])
            samples, sr = _read_wav(clean)
            words = align_words(text, samples, sr)
            src = clean
        else:
            src = out_dir / f"scene_{idx:02d}.mp3"
            words = _edge(text, voice_cfg["name"], voice_cfg.get("rate", "+0%"), src)
    except Exception as e:
        raise TTSError(f"No se pudo sintetizar la voz de la escena {idx + 1} («{text[:60]}…»): {e}. "
                       "Revisa tu conexión o prueba otra voz en Configuración.") from e
    ffmpeg.run(["-i", src, "-af", f"apad=pad_dur={gap}", "-ar", SAMPLE_RATE, "-ac", 1, "-c:a", "pcm_s16le", wav])
    return SceneAudio(wav=wav, duration=_wav_duration(wav), words=words)


def concat_wavs(parts: list[Path], out: Path) -> float:
    with wave.open(str(out), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(SAMPLE_RATE)
        for p in parts:
            with wave.open(str(p), "rb") as src:
                dst.writeframes(src.readframes(src.getnframes()))
    return _wav_duration(out)
