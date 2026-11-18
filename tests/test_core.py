"""Pruebas rápidas sin red ni claves:  venv\\Scripts\\python.exe -m unittest discover -s tests"""
from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import learning, music, render, sfx, tts  # noqa: E402


def _speech(segments, sr=44100, total=None):
    """Audio sintético: tono modulado en los tramos dados (simula voz) y silencio en el resto."""
    total = total or segments[-1][1] + 0.2
    x = np.zeros(int(total * sr), dtype=np.float32)
    for a, b in segments:
        t = np.arange(int((b - a) * sr)) / sr
        x[int(a * sr):int(a * sr) + len(t)] = 0.5 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
    return x, sr


class AlignTest(unittest.TestCase):
    def test_segments_detected(self):
        x, sr = _speech([(0.0, 1.5), (1.9, 3.0), (3.4, 4.2)])
        segs = tts.speech_segments(x, sr)
        self.assertEqual(len(segs), 3)
        self.assertAlmostEqual(segs[1][0], 1.9, delta=0.05)

    def test_phrases_follow_pauses(self):
        x, sr = _speech([(0.0, 1.5), (1.9, 3.0)])
        words = tts.align_words("Hola a todos, hoy cocinamos lentejas.", x, sr)
        self.assertEqual([w.text for w in words], ["Hola", "a", "todos", "hoy", "cocinamos", "lentejas"])
        hoy = words[3]
        self.assertAlmostEqual(hoy.start, 1.9, delta=0.05)  # la segunda frase empieza tras la pausa
        self.assertTrue(all(w.end > w.start for w in words))
        self.assertTrue(all(a.end <= b.start + 1e-6 for a, b in zip(words, words[1:])))

    def test_mismatch_falls_back_to_proportional(self):
        x, sr = _speech([(0.0, 3.0)])
        words = tts.align_words("Uno, dos, tres, cuatro.", x, sr)
        self.assertEqual(len(words), 4)
        self.assertLessEqual(words[-1].end, 3.05)


class AudioTest(unittest.TestCase):
    def test_music_every_mood(self):
        with tempfile.TemporaryDirectory() as d:
            for mood in music.MOODS:
                out = Path(d) / f"{mood}.wav"
                info = music.compose(mood, 8, out, seed=1)
                with wave.open(str(out)) as w:
                    dur = w.getnframes() / w.getframerate()
                    data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                self.assertGreaterEqual(dur, 8, mood)
                self.assertGreater(np.abs(data).max(), 1000, mood)  # no es silencio
                self.assertFalse(np.isnan(data.astype(float)).any())
                self.assertEqual(info["mood"], mood)

    def test_sfx_track(self):
        class Sc:
            def __init__(self, anim):
                self.animation = anim

        class Plan:
            scenes = [Sc(object()), Sc(None), Sc(object())]

        ev = sfx.events_for(Plan(), [0.0, 4.0, 9.0], portrait=True)
        self.assertEqual([n for _, n in ev], ["hit", "swish", "whoosh"])
        with tempfile.TemporaryDirectory() as d:
            out = sfx.build_track(ev, 12.0, Path(d) / "fx.wav")
            with wave.open(str(out)) as w:
                self.assertEqual(w.getframerate(), sfx.SR)
                self.assertGreaterEqual(w.getnframes() / sfx.SR, 12.0)


class SubtitleTest(unittest.TestCase):
    def test_ass_chunks(self):
        words = [tts.Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate("uno dos tres cuatro cinco seis".split())]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.ass"
            render.write_ass([words], [0.0], 1080, 1920, True, "Arial", out)
            text = out.read_text(encoding="utf-8-sig")
        self.assertEqual(text.count("Dialogue:"), 2)  # 3 palabras por línea en vertical
        self.assertIn("UNO", text)


class LearningTest(unittest.TestCase):
    def test_traits_buckets(self):
        t = learning._traits({"duration": 42, "format": "short", "animations": 3, "music_mood": "alegre"})
        self.assertEqual(t["duration_short"], "short 35-50 s")  # la duración se compara solo dentro del formato
        self.assertEqual(t["animations"], "varias (3+)")
        self.assertEqual(t["music_mood"], "alegre")


if __name__ == "__main__":
    unittest.main()
