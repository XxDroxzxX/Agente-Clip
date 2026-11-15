"""Pruebas sin red ni navegador de la publicación por navegador."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente.publish import browser  # noqa: E402


class StatusTest(unittest.TestCase):
    def test_status_roundtrip_and_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(browser, "ROOT", Path(tmp)):
            self.assertEqual(browser.status("youtube"), {"connected": False})
            browser._save_status("youtube", connected=True, error=None)
            browser.profile_dir("youtube").mkdir(parents=True)
            self.assertTrue(browser.status("youtube")["connected"])
            browser.disconnect("youtube")
            self.assertFalse(browser.status("youtube")["connected"])
            self.assertFalse(browser.profile_dir("youtube").exists())

    def test_session_cookie_detection(self):
        ctx = mock.Mock()
        ctx.cookies.return_value = [{"name": "SAPISID", "domain": ".youtube.com", "value": "x"}]
        self.assertTrue(browser._logged_in(ctx, "youtube"))
        self.assertFalse(browser._logged_in(ctx, "tiktok"))

    def test_upload_progress_text(self):
        uploading = lambda t: bool(browser._UPLOADING.search(t) and browser._PERCENT.search(t)
                                   and int(browser._PERCENT.search(t).group(1)) < 100)
        self.assertTrue(uploading("Subiendo 45 % ... Quedan 2 minutos"))
        self.assertTrue(uploading("Uploading 7%"))
        self.assertFalse(uploading("Subida completada"))
        self.assertFalse(uploading("Procesando la versión en SD..."))


if __name__ == "__main__":
    unittest.main()
