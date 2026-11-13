"""Música de fondo automática, acorde a cada video.

Fuentes (Configuración → Video y voz → Música):
  - generada: compositor procedural propio. Gratis, sin conexión y sin derechos de autor.
              Arma progresión de acordes, bajo, colchón, arpegios y batería según el estado
              de ánimo que eligió la IA del guion, con la duración exacta del video.
  - lyria:    música con IA de Google (Gemini API, de pago: ~US$0.04-0.08 por pieza).
              Si falla, se usa la generada.
  - carpeta:  un archivo al azar de assets/music (si está vacía, se usa la generada).
"""
from __future__ import annotations

import base64
import random
import wave
import zlib
from pathlib import Path
from typing import Callable

import numpy as np
import requests

from .paths import MUSIC_DIR

SR = 44100
MOODS = ("energetico", "alegre", "inspirador", "tranquilo", "misterioso", "emotivo", "tecnologico")

# Acordes como (semitonos desde la tónica, calidad)
MAJ = {"I": (0, "maj"), "ii": (2, "min"), "iii": (4, "min"), "IV": (5, "maj"), "V": (7, "maj"), "vi": (9, "min"),
       "Imaj7": (0, "maj7"), "vi7": (9, "min7"), "IVmaj7": (5, "maj7"), "V7": (7, "dom7"), "ii7": (2, "min7")}
MIN = {"i": (0, "min"), "III": (3, "maj"), "iv": (5, "min"), "v": (7, "min"), "V": (7, "maj"), "VI": (8, "maj"),
       "VII": (10, "maj"), "i7": (0, "min7"), "iv7": (5, "min7")}
QUALITY = {"maj": (0, 4, 7), "min": (0, 3, 7), "maj7": (0, 4, 7, 11), "min7": (0, 3, 7, 10), "dom7": (0, 4, 7, 10)}

PRESETS = {
    #              bpm       progresiones posibles                                   batería     bajo      arpegio   piano
    "energetico": dict(bpm=(120, 128), keys=MIN, progs=[["i", "VI", "III", "VII"], ["i", "VII", "VI", "VII"]],
                       drums="four", bass="pump", arp=16, keys_instr=False),
    "alegre": dict(bpm=(108, 116), keys=MAJ, progs=[["I", "V", "vi", "IV"], ["I", "IV", "vi", "V"]],
                   drums="pop", bass="root8", arp=8, keys_instr=False),
    "inspirador": dict(bpm=(96, 104), keys=MAJ, progs=[["vi", "IV", "I", "V"], ["I", "V", "vi", "IV"]],
                       drums="half", bass="long", arp=8, keys_instr=False),
    "tranquilo": dict(bpm=(76, 84), keys=MAJ, progs=[["Imaj7", "vi7", "IVmaj7", "V7"], ["ii7", "V7", "Imaj7", "vi7"]],
                      drums="lofi", bass="root", arp=0, keys_instr=True),
    "misterioso": dict(bpm=(86, 94), keys=MIN, progs=[["i", "VI", "iv", "V"], ["i", "iv", "i", "V"]],
                       drums="sparse", bass="drone", arp=8, keys_instr=False),
    "emotivo": dict(bpm=(68, 76), keys=MIN, progs=[["i", "VI", "III", "VII"], ["i7", "iv7", "VI", "V"]],
                    drums="none", bass="long", arp=8, keys_instr=True),
    "tecnologico": dict(bpm=(106, 114), keys=MIN, progs=[["i", "i", "VI", "VII"], ["i", "VI", "iv", "V"]],
                        drums="electro", bass="pulse16", arp=16, keys_instr=False),
}


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


class Composer:
    def __init__(self, mood: str, duration: float, seed: int):
        self.p = PRESETS.get(mood, PRESETS["inspirador"])
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.bpm = self.rng.randint(*self.p["bpm"])
        self.beat = 60.0 / self.bpm
        self.bar = self.beat * 4
        self.root = 48 + self.rng.randint(0, 11)  # tónica en la 3.ª octava
        self.prog = [self.p["keys"][c] for c in self.rng.choice(self.p["progs"])]
        self.n_bars = int(np.ceil((duration + 2.0) / self.bar))
        self.length = int((self.n_bars * self.bar + 2.0) * SR)
        # buses: «music» (armonía y bajo, se agacha con el bombo), «drums» y «send» (entrada de la reverb)
        self.bus = {k: np.zeros((self.length, 2)) for k in ("music", "drums", "send")}
        self.kicks: list[float] = []

    # ── utilidades ──────────────────────────────────
    def _add(self, sig: np.ndarray, t0: float, gain: float = 1.0, pan: float = 0.0,
             bus: str = "music", send: float = 0.0):
        s = int(max(0.0, t0) * SR)
        if s >= self.length:
            return
        sig = sig[: self.length - s]
        lr = np.stack([sig * (1 - max(0.0, pan)), sig * (1 + min(0.0, pan))], axis=1) * gain
        self.bus[bus][s:s + len(sig)] += lr
        if send:
            self.bus["send"][s:s + len(sig)] += lr * send

    def _vel(self, spread: float = 0.18) -> float:
        """Variación de intensidad nota a nota: lo que separa a un músico de una máquina."""
        return 1.0 + self.rng.uniform(-spread, spread)

    def _jit(self, ms: float = 6.0) -> float:
        return self.rng.uniform(-ms, ms) / 1000.0

    @staticmethod
    def _t(dur: float) -> np.ndarray:
        return np.arange(int(dur * SR)) / SR

    def chord_notes(self, chord, center=60) -> list[int]:
        off, q = chord
        out = []
        for iv in QUALITY[q]:
            pc = (self.root + off + iv) % 12
            note = pc + 12 * round((center - pc) / 12)  # octava más cercana al centro: conducción de voces suave
            out.append(note)
        return sorted(out)

    # ── instrumentos ────────────────────────────────
    def pad(self, notes, t0, dur, gain):
        t = self._t(dur + 0.8)
        att, rel = min(0.6, dur * 0.4), 0.8
        env = np.clip(t / att, 0, 1) * np.clip((dur + rel - t) / rel, 0, 1)
        swell = 0.85 + 0.15 * np.sin(2 * np.pi * t / max(dur, 0.5) - np.pi / 2)  # respira dentro del compás
        for side, cents in ((-0.7, -7), (0.7, 7)):
            sig = np.zeros_like(t)
            for n in notes:
                f = _hz(n) * 2 ** (cents / 1200)
                for k, a in ((1, 1.0), (2, 0.38), (3, 0.16), (4, 0.07)):  # pocos armónicos altos: más cálido
                    sig += a * np.sin(2 * np.pi * f * k * t + k + 0.3 * np.sin(2 * np.pi * 0.4 * t))
            self._add(sig * env * swell / len(notes), t0, gain, side, send=0.55)

    def pluck(self, note, t0, gain, pan=0.0, decay=6.0):
        t = self._t(0.9)
        f = _hz(note)
        # pasa-bajos con LFO lento (ciclo de 4 compases): el timbre abre y cierra, no es estático
        cutoff = 800 + 900 * (0.5 + 0.5 * np.sin(2 * np.pi * t0 / (self.bar * 4)))
        sig = np.zeros_like(t)
        for k in range(1, 9):
            fk = f * k
            if fk > 9000:
                break
            lp = 1.0 / (1.0 + (fk / cutoff) ** 4)
            sig += (1.0 / k) * lp * np.sin(2 * np.pi * fk * t) * np.exp(-t * decay * (1 + 0.5 * k))
        sig *= np.clip(t / 0.004, 0, 1)
        g = gain * self._vel()
        t0 += self._jit(4)
        self._add(sig, t0, g, pan, send=0.35)
        for i, fb in enumerate((0.32, 0.15, 0.06), 1):  # eco a 3/8 de pulso
            self._add(sig, t0 + i * self.beat * 0.75, g * fb, -pan if i % 2 else pan, send=0.5)

    def epiano(self, notes, t0, gain):
        t = self._t(1.8)
        sig = np.zeros_like(t)
        for n in notes:
            f = _hz(n + 12)
            sig += (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 6)
                    + 0.08 * np.sin(2 * np.pi * 7.1 * f * t) * np.exp(-t * 18))
        sig *= np.exp(-t * 1.6) * np.clip(t / 0.005, 0, 1) / len(notes)
        self._add(sig, t0 + self._jit(8), gain * self._vel(0.12), 0.15, send=0.4)

    def bass(self, note, t0, dur, gain):
        t = self._t(dur)
        f = _hz(note - 12)
        sig = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t) + 0.1 * np.sin(2 * np.pi * 3 * f * t)
        env = np.clip(t / 0.008, 0, 1) * (0.6 + 0.4 * np.exp(-t * 5)) * np.clip((dur - t) / 0.03, 0, 1)
        self._add(sig * env, t0, gain)

    def kick(self, t0, gain):
        t = self._t(0.5)
        f = 52 + 120 * np.exp(-t * 30)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 6.5)  # cuerpo en 55-80 Hz
        click = np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 400) * 0.25     # ataque audible en celulares
        sig = np.tanh(1.6 * (body + click))
        self.kicks.append(t0)
        self._add(sig, t0, gain * self._vel(0.06), bus="drums")

    def snare(self, t0, gain, soft=False):
        t = self._t(0.3)
        noise = np.diff(self.np_rng.standard_normal(len(t) + 1))
        tone = np.sin(2 * np.pi * 190 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)
        sig = 0.5 * noise * np.exp(-t * (26 if soft else 17)) + 0.4 * tone * np.exp(-t * 28)
        self._add(sig, t0 + self._jit(3), gain * self._vel(0.1), bus="drums", send=0.2)

    def hat(self, t0, gain, open_=False, pan=0.25):
        t = self._t(0.25 if open_ else 0.06)
        # metálico tipo caja de ritmos: cuadradas en proporciones inarmónicas + ruido, sin graves
        metal = sum(np.sign(np.sin(2 * np.pi * fr * t)) for fr in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0))
        raw = 0.5 * metal / 6 + 0.5 * self.np_rng.standard_normal(len(t))
        sig = np.diff(np.concatenate([[0.0], raw]))
        self._add(sig * np.exp(-t * (13 if open_ else 65)), t0 + self._jit(5), gain * self._vel(0.25), pan,
                  bus="drums")

    # ── arreglo ─────────────────────────────────────
    def compose(self) -> np.ndarray:
        p, B, b = self.p, self.bar, self.beat
        last = self.n_bars - 1
        for bar in range(self.n_bars):
            t0 = 1.0 + bar * B  # 1 s de margen inicial (entra con fundido)
            chord = self.prog[bar % len(self.prog)]
            notes = self.chord_notes(chord)
            root = (self.root + chord[0]) % 12 + 48  # bass() baja una octava: 65-123 Hz, audible en celulares
            intro, outro = bar < 2, bar >= last - 1
            full = not intro and not outro
            lift = full and bar % 8 == 7  # cada 8 compases, un respiro antes de repetir

            if p["keys_instr"]:
                for beat_pos in ((0, 2.5) if p["drums"] == "lofi" else (0,)):
                    self.epiano(notes, t0 + beat_pos * b, 0.32)
            self.pad(notes, t0, B, 0.22 if p["keys_instr"] else 0.28)

            if not intro:
                self._bass_line(root, t0, outro)
            if p["arp"] and not (intro and bar == 0):
                step = b * 4 / p["arp"]
                seq = notes + [n + 12 for n in notes]
                k = 0
                for i in range(p["arp"]):
                    if p["arp"] == 16 and i % 4 == 3 and self.rng.random() < 0.3:
                        continue  # variación rítmica
                    self.pluck(seq[k % len(seq)] + 12, t0 + i * step, 0.11 if full else 0.07, pan=0.3 if i % 2 else -0.3)
                    k += 1
            if full and not lift:
                self._drums(t0)
                if bar % 4 == 3 and p["drums"] not in ("none", "sparse"):
                    for i in range(4):  # redoble corto que anuncia la siguiente frase
                        self.snare(t0 + 3 * b + i * b / 4, 0.12 + 0.05 * i, soft=True)
            elif lift:
                for i in range(8):
                    self.hat(t0 + i * b / 2, 0.06 + 0.02 * i)
        return self._master()

    def _bass_line(self, root, t0, outro):
        b, kind = self.beat, self.p["bass"]
        if outro or kind in ("long", "drone"):
            self.bass(root, t0, self.bar * 0.98, 0.45)
        elif kind == "root":
            self.bass(root, t0, b * 1.5, 0.5)
            self.bass(root, t0 + b * 2.5, b * 1.2, 0.4)
        elif kind == "root8":
            for i in range(8):
                self.bass(root + (12 if i in (3, 7) else 0), t0 + i * b / 2, b * 0.45, 0.42)
        elif kind == "pump":
            for i in range(4):
                self.bass(root, t0 + i * b + b / 2, b * 0.45, 0.5)
        elif kind == "pulse16":
            for i in range(16):
                self.bass(root + (7 if i % 8 == 6 else 0), t0 + i * b / 4, b * 0.22, 0.36)

    def _drums(self, t0):
        b, kind = self.beat, self.p["drums"]
        if kind == "four":
            for i in range(4):
                self.kick(t0 + i * b, 0.75)
                self.hat(t0 + i * b + b / 2, 0.07, open_=True)
            for i in (1, 3):
                self.snare(t0 + i * b, 0.35)
            for i in range(16):
                self.hat(t0 + i * b / 4, 0.035, pan=-0.2)
        elif kind == "pop":
            for x in (0, 1.5, 2.5):
                self.kick(t0 + x * b, 0.7)
            for i in (1, 3):
                self.snare(t0 + i * b, 0.33)
            for i in range(8):
                self.hat(t0 + i * b / 2, 0.07)
        elif kind == "half":
            self.kick(t0, 0.7)
            self.kick(t0 + 2.5 * b, 0.5)
            self.snare(t0 + 2 * b, 0.32)
            for i in range(8):
                self.hat(t0 + i * b / 2, 0.05)
        elif kind == "lofi":
            swing = b * 0.08
            self.kick(t0, 0.7)
            self.kick(t0 + 2.75 * b, 0.5)
            for i in (1, 3):
                self.snare(t0 + i * b, 0.3, soft=True)
            for i in range(8):
                self.hat(t0 + i * b / 2 + (swing if i % 2 else 0), 0.045)
        elif kind == "sparse":
            self.kick(t0, 0.5)
            for i in range(8):
                self.hat(t0 + i * b / 2, 0.03 if i % 2 else 0.05)
        elif kind == "electro":
            for x in (0, 1.75, 2.5):
                self.kick(t0 + x * b, 0.7)
            for i in (1, 3):
                self.snare(t0 + i * b, 0.3)
            for i in range(16):
                self.hat(t0 + i * b / 4, 0.045 if i % 2 == 0 else 0.025)

    def _pump(self) -> np.ndarray:
        """Sidechain: la armonía baja un poco con cada bombo y vuelve en ~0,2 s (el «bombeo» rítmico)."""
        env = np.ones(self.length)
        shape = 1 - 0.28 * np.exp(-self._t(0.22) / 0.07)
        for k in self.kicks:
            s = int(k * SR)
            e = min(self.length, s + len(shape))
            if s < self.length:
                env[s:e] = np.minimum(env[s:e], shape[: e - s])
        return env[:, None]

    def _master(self) -> np.ndarray:
        wet = np.stack([_conv(self.bus["send"][:, c], _reverb_ir(seed=c + 7)) for c in (0, 1)], axis=1)
        drums = np.stack([_conv(self.bus["drums"][:, c], _EQ_DRUMS, len(_EQ_DRUMS) // 2) for c in (0, 1)], axis=1)
        st = (self.bus["music"] + wet * 0.35) * self._pump() + drums
        # deja hueco a la voz (baja 2-4 kHz) y quita subgraves inútiles
        st = np.stack([_conv(st[:, c], _EQ_BUS, len(_EQ_BUS) // 2) for c in (0, 1)], axis=1)
        st = np.tanh(st * 1.2)  # «pegamento» suave
        fade_in, fade_out = int(1.0 * SR), int(2.5 * SR)
        st[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
        end = int((1.0 + self.n_bars * self.bar) * SR)
        st = st[:end]
        st[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
        peak = np.max(np.abs(st)) or 1.0
        return st / peak * 0.89


# ── procesamiento (FIR y reverb por convolución en bloques) ───

def _conv(x: np.ndarray, h: np.ndarray, delay: int = 0, block: int = 1 << 16) -> np.ndarray:
    """Convolución overlap-add. Devuelve len(x) muestras desde `delay` (para compensar FIR de fase lineal)."""
    m = len(h)
    nfft = 1 << int(np.ceil(np.log2(block + m - 1)))
    H = np.fft.rfft(h, nfft)
    out = np.zeros(len(x) + m - 1)
    for i in range(0, len(x), block):
        seg = x[i:i + block]
        y = np.fft.irfft(np.fft.rfft(seg, nfft) * H, nfft)[: len(seg) + m - 1]
        out[i:i + len(y)] += y
    return out[delay:delay + len(x)]


def _fir(curve, taps: int = 4097) -> np.ndarray:
    """FIR de fase lineal a partir de una curva de ganancia en dB (función de la frecuencia en Hz)."""
    n = 1 << 14
    f = np.fft.rfftfreq(n, 1 / SR)
    h = np.fft.irfft(10 ** (curve(f) / 20), n)
    return np.roll(h, taps // 2)[:taps] * np.hanning(taps)


def _bell(f, f0, gain_db, octaves):
    return gain_db * np.exp(-0.5 * (np.log2(np.maximum(f, 1) / f0) / (octaves / 2)) ** 2)


def _hp(f, f0):
    return -24 * np.clip(np.log2(f0 / np.maximum(f, 1)), 0, None)  # 24 dB/oct bajo f0


_EQ_BUS = _fir(lambda f: _bell(f, 3000, -5.0, 1.3) + _bell(f, 320, -2.5, 1.0) + _hp(f, 35))
_EQ_DRUMS = _fir(lambda f: _bell(f, 75, 3.5, 1.0))


def _reverb_ir(seconds: float = 1.7, seed: int = 0) -> np.ndarray:
    """Respuesta de sala sintética: ruido con caída exponencial, cálida (sin agudos ni graves)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t * 3.8)
    ir[: int(0.012 * SR)] = 0  # pre-delay: separa la reverb del sonido directo
    tone = _fir(lambda f: _bell(f, 9000, -12, 3) + _hp(f, 250), 513)
    ir = np.convolve(ir, tone, mode="same")
    return ir / np.sqrt((ir ** 2).sum())


def compose(mood: str, duration: float, out: Path, seed: int) -> dict:
    c = Composer(mood, duration, seed)
    audio = c.compose()
    pcm = (audio * 32767).astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return {"bpm": c.bpm, "mood": mood if mood in PRESETS else "inspirador"}


def lyria(prompt: str, duration: float, out_dir: Path) -> Path:
    """Música con Lyria (Gemini API, de pago). Devuelve el archivo de audio."""
    from . import gemini
    model = "lyria-3-clip-preview" if duration <= 32 else "lyria-3.5"
    text = (f"{prompt}. Instrumental only, no vocals. Background music for a social media video"
            + ("." if duration <= 32 else f", about {int(duration)} seconds long."))
    r = requests.post(f"{gemini.API}/interactions", json={"model": model, "input": text}, timeout=600,
                      headers={"x-goog-api-key": gemini.api_key(), "Api-Revision": gemini.REVISION})
    if not r.ok:
        msg = gemini._error_msg(r)
        if r.status_code == 429 or "billing" in msg.lower() or "free tier" in msg.lower():
            raise RuntimeError("Lyria es de pago: activa la facturación en tu proyecto de Google AI Studio.")
        raise RuntimeError(f"Lyria respondió con error {r.status_code}: {msg[:160]}")
    for step in r.json().get("steps") or []:
        for block in step.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "audio" and block.get("data"):
                mime = block.get("mime_type") or "audio/mpeg"
                dest = out_dir / ("music.wav" if "wav" in mime else "music.mp3")
                dest.write_bytes(base64.b64decode(block["data"]))
                return dest
    raise RuntimeError("Lyria no devolvió audio.")


def for_item(cfg: dict, brief, duration: float, item_dir: Path, seed_key: str,
             log: Callable[[str, str], None]) -> Path | None:
    """Música de fondo para un video. brief: MusicBrief del guion (o None)."""
    v = cfg["video"]
    if not v.get("music", True):
        return None
    source = v.get("music_source", "generada")
    mood = getattr(brief, "mood", None) or "inspirador"
    prompt = getattr(brief, "prompt", None) or f"{mood} instrumental background music"
    seed = zlib.crc32(seed_key.encode())

    if source == "carpeta":
        files = [p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
        if files:
            return random.Random(seed).choice(files)
        log("assets/music está vacía: se genera la música automáticamente.", "info")
    if source == "lyria":
        try:
            f = lyria(prompt, duration, item_dir)
            log(f"Música con Lyria: «{prompt[:80]}».", "info")
            return f
        except Exception as e:
            log(f"{e} Se usa la música generada.", "warn")
    out = item_dir / "music.wav"
    info = compose(mood, duration, out, seed)
    log(f"Música generada: estado «{info['mood']}», {info['bpm']} BPM, {duration:.0f} s.", "info")
    return out
