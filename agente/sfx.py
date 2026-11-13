"""Efectos de sonido sintetizados (sin archivos ni derechos de autor).

- whoosh: barrido de ruido filtrado; acompaña la entrada de cada animación.
- swish: versión corta y suave para los cambios de escena.
- hit: golpe grave breve para el gancho inicial.
Se colocan en una pista aparte que se mezcla con la voz y la música en el montaje.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000


def _bandpass_sweep(noise: np.ndarray, f0: float, f1: float, q: float = 1.6) -> np.ndarray:
    """Filtro pasa-banda (biquad) con frecuencia central que se desliza de f0 a f1."""
    n = len(noise)
    freqs = np.geomspace(f0, f1, n)
    out = np.zeros(n)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(n):
        w0 = 2 * np.pi * freqs[i] / SR
        alpha = np.sin(w0) / (2 * q)
        b0, a0 = alpha, 1 + alpha
        a1, a2 = -2 * np.cos(w0), 1 - alpha
        x0 = noise[i]
        y0 = (b0 * x0 - b0 * x2 - a1 * y1 - a2 * y2) / a0
        out[i] = y0
        x2, x1, y2, y1 = x1, x0, y1, y0
    return out


def whoosh(dur: float = 0.5, rising: bool = True, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    f0, f1 = (300, 3500) if rising else (3500, 300)
    sig = _bandpass_sweep(rng.standard_normal(n), f0, f1)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t ** 0.7) ** 2  # sube rápido, cae suave
    sig = sig * env
    return sig / (np.abs(sig).max() + 1e-9)


def hit(dur: float = 0.6) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = 110 * np.exp(-t * 6) + 45  # tono grave que cae
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)
    click = np.random.default_rng(3).standard_normal(n) * np.exp(-t * 90) * 0.3
    sig = np.tanh(1.8 * (body + click))
    return sig / (np.abs(sig).max() + 1e-9)


SOUNDS = {
    "whoosh": lambda: whoosh(0.5, True, 1) * 0.55,
    "swish": lambda: whoosh(0.28, False, 2) * 0.28,
    "hit": lambda: hit() * 0.6,
}


def build_track(events: list[tuple[float, str]], total: float, out: Path) -> Path | None:
    """events: [(segundo, nombre)]. El sonido termina justo en el segundo indicado (el whoosh «llega» con la animación)."""
    if not events:
        return None
    n = int(SR * (total + 1))
    track = np.zeros((n, 2))
    cache: dict[str, np.ndarray] = {}
    for k, (t, name) in enumerate(sorted(events)):
        if name not in SOUNDS:
            continue
        s = cache.setdefault(name, SOUNDS[name]())
        lead = 0.0 if name == "hit" else len(s) / SR * 0.7  # el pico del barrido coincide con la entrada
        i = max(0, int((t - lead) * SR))
        j = min(n, i + len(s))
        pan = 0.25 if k % 2 else -0.25  # alterna de lado para que no suenen idénticos
        seg = s[: j - i]
        track[i:j, 0] += seg * (1 - pan)
        track[i:j, 1] += seg * (1 + pan)
    peak = np.abs(track).max()
    if peak > 0.95:
        track *= 0.95 / peak
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((track * 32767).astype(np.int16).tobytes())
    return out


def events_for(plan, offsets: list[float], portrait: bool) -> list[tuple[float, str]]:
    """Dónde suenan los efectos: golpe en el gancho, whoosh con cada animación y, en shorts, un swish suave en cada cambio de escena."""
    ev: list[tuple[float, str]] = []
    for i, (sc, t) in enumerate(zip(plan.scenes, offsets)):
        if getattr(sc, "animation", None) is not None:
            ev.append((t + 0.05, "hit" if i == 0 else "whoosh"))
        elif portrait and i > 0:
            ev.append((t, "swish"))
    return ev
