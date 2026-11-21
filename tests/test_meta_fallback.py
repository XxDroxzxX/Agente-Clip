"""Segunda vía cuando falla la API de Meta (sin red ni navegador)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import pipeline  # noqa: E402
from agente.publish import browser, facebook, instagram  # noqa: E402


class FakeRun:
    def __init__(self, credits=("Generado con IA",)):
        self.state = {"items": {"short_1": {"credits": list(credits)}}}
        self.warnings = []

    def warn(self, msg, step=None):
        self.warnings.append(msg)


P = {"facebook_graph_version": "v24.0", "meta_fallback": True, "browser_visible": False}
OK = {"platform_id": "1", "url": "u", "privacy": "public", "note": ""}


class InstagramFallbackTest(unittest.TestCase):
    def _go(self, api, connected=True, p=P):
        run = FakeRun()
        with mock.patch.object(instagram, "upload_reel", side_effect=api), \
                mock.patch.object(browser, "status", return_value={"connected": connected}), \
                mock.patch.object(browser, "upload_instagram", return_value=dict(OK)) as web:
            try:
                res = pipeline._instagram(run, p, Path("v.mp4"), "texto", lambda x: None, "short_1")
            except RuntimeError as e:
                res = e
        return res, web, run

    def test_api_ok_does_not_use_browser(self):
        res, web, _ = self._go(lambda *a: dict(OK))
        web.assert_not_called()

    def test_api_error_never_uses_browser(self):
        # Instagram suspendió la cuenta por «comportamientos automatizados» (2026-11-19): nunca más por navegador
        res, web, _ = self._go(RuntimeError("ProcessingFailedError"))
        self.assertIsInstance(res, RuntimeError)
        self.assertIn("celular", str(res))
        web.assert_not_called()

    def test_uncertain_publish_is_never_repeated(self):
        res, web, _ = self._go(instagram.UncertainPublish("sin respuesta"))
        self.assertIsInstance(res, instagram.UncertainPublish)
        web.assert_not_called()

    def test_instagram_not_a_browser_platform(self):
        self.assertNotIn("instagram", browser.PLATFORMS)  # ni iniciar sesión ni publicar con el navegador

    def test_fallback_can_be_disabled(self):
        res, web, _ = self._go(RuntimeError("fallo"), p={**P, "meta_fallback": False})
        self.assertIsInstance(res, RuntimeError)
        web.assert_not_called()


class FacebookFallbackTest(unittest.TestCase):
    def _go(self, reel_error):
        plan = mock.Mock(title="t")
        with mock.patch.object(facebook, "upload_reel", side_effect=reel_error), \
                mock.patch.object(facebook, "upload_video", return_value=dict(OK)) as vid:
            try:
                res = pipeline._facebook(FakeRun(), P, Path("v.mp4"), plan, "d", "#x", lambda x: None, "short_1")
            except RuntimeError as e:
                res = e
        return res, vid

    def test_reel_error_goes_as_page_video(self):
        res, vid = self._go(RuntimeError("Facebook Reels (subida): fallo"))
        vid.assert_called_once()
        self.assertIn("video de la página", res["note"])

    def test_error_when_confirming_is_not_repeated(self):
        res, vid = self._go(RuntimeError("Facebook Reels (publicación): sin respuesta"))
        self.assertIsInstance(res, RuntimeError)
        vid.assert_not_called()


class DescriptionCreditsTest(unittest.TestCase):
    def test_ai_shots_are_not_declared(self):
        # decisión del usuario: no declarar contenido IA en las publicaciones
        self.assertEqual(pipeline.credits_line(["Generado con IA"]), "")
        line = pipeline.credits_line(["Generado con IA", "Pexels: Ana", "Generado con IA"])
        self.assertEqual(line, "\n\nMaterial visual: Pexels: Ana")
        self.assertNotIn("IA", line)


if __name__ == "__main__":
    unittest.main()
