"""Narración con voces neuronales (edge-tts) y tiempos por palabra para subtítulos."""
from __future__ import annotations

import asyncio
import wave
from dataclasses import dataclass, field
from pathlib import Path

import edge_tts

from . import ffmpeg

SAMPLE_RATE = 44100
SCENE_GAP = 0.25  # silencio entre escenas (s)


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


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def synthesize_scene(text: str, voice: str, rate: str, out_dir: Path, idx: int, gap: float = SCENE_GAP) -> SceneAudio:
    mp3 = out_dir / f"scene_{idx:02d}.mp3"
    wav = out_dir / f"scene_{idx:02d}.wav"
    last_err = None
    for _ in range(3):
        try:
            words = asyncio.run(_speak(text, voice, rate, mp3))
            break
        except Exception as e:  # red inestable: reintenta
            last_err = e
    else:
        raise RuntimeError(f"No se pudo sintetizar la voz: {last_err}")
    ffmpeg.run(["-i", mp3, "-af", f"apad=pad_dur={gap}", "-ar", SAMPLE_RATE, "-ac", 1, "-c:a", "pcm_s16le", wav])
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
