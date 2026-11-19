"""Muestras para elegir viendo/escuchando: imágenes de estilo visual y frases de muestra de cada voz."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agente import style_previews, tts
from agente.catalog import VISUAL_STYLES


class StylePreviewTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(style_previews.slug("Cámara de seguridad / metraje encontrado"),
                         "camara-de-seguridad-metraje-encontrado")
        self.assertEqual(style_previews.preview_name("Terror / oscuro"), "terror-oscuro.jpg")

    def test_unique_names(self):
        names = [style_previews.preview_name(l) for _, l in VISUAL_STYLES]
        self.assertEqual(len(names), len(set(names)))

    def test_available_only_existing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(style_previews, "STYLE_DIR", Path(d)):
            value, label = VISUAL_STYLES[1]
            (Path(d) / style_previews.preview_name(label)).write_bytes(b"x")
            self.assertEqual(style_previews.available(), {value: style_previews.preview_name(label)})


class VoicePreviewTest(unittest.TestCase):
    def test_cached_once(self):
        calls = []

        def fake_scene(text, cfg, out_dir, idx, gap=0.0, engine=None, lang="es"):
            calls.append((engine, cfg["name"], text))
            wav = Path(out_dir) / "s.wav"
            wav.write_bytes(b"RIFF")
            return tts.SceneAudio(wav=wav, duration=1.0, words=[])

        def fake_ffmpeg(args, **kw):
            Path(args[-1]).write_bytes(b"ID3")

        with tempfile.TemporaryDirectory() as d, mock.patch("agente.paths.CACHE_DIR", Path(d)), \
                mock.patch.object(tts, "synthesize_scene", side_effect=fake_scene), \
                mock.patch.object(tts.ffmpeg, "run", side_effect=fake_ffmpeg):
            a = tts.preview("edge", "es-MX-JorgeNeural", "es")
            b = tts.preview("edge", "es-MX-JorgeNeural", "es")
            c = tts.preview("edge", "en-US-AndrewNeural", "en")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(calls), 2)  # la segunda vez sale de la caché
        self.assertIn("Hola", calls[0][2])

    def test_server_rejects_bad_input(self):
        import app.server as srv
        from fastapi import HTTPException
        for args in (("x", "Puck", "es"), ("edge", "../../etc", "es"), ("edge", "es-MX-JorgeNeural", "zz")):
            with self.assertRaises(HTTPException):
                srv.voice_preview(*args)


if __name__ == "__main__":
    unittest.main()
