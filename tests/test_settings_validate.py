"""Validación de la configuración y nombres legibles del catálogo (sin red)."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import catalog  # noqa: E402
from agente import settings as S  # noqa: E402
from agente.util import redact  # noqa: E402


class ValidateTest(unittest.TestCase):
    def _cfg(self, **sections):
        c = copy.deepcopy(S.DEFAULTS)
        for sec, vals in sections.items():
            c[sec].update(vals)
        return c

    def test_defaults_are_valid(self):
        _, fixes = S.validate(self._cfg())
        self.assertEqual(fixes, [])

    def test_region_alias_and_unknown(self):
        c, _ = S.validate(self._cfg(content={"region_code": "usa"}))
        self.assertEqual(c["content"]["region_code"], "US")
        c, fixes = S.validate(self._cfg(content={"region_code": "XX"}))
        self.assertEqual(c["content"]["region_code"], "")
        self.assertTrue(fixes)

    def test_voice_follows_language(self):
        c, _ = S.validate(self._cfg(content={"language": "pt"}, voice={"name": "es-MX-JorgeNeural"}))
        self.assertEqual(c["voice"]["name"], "pt-BR-AntonioNeural")

    def test_numbers_and_enums(self):
        c, fixes = S.validate(self._cfg(video={"music_volume": "3", "shorts_count": -2, "quality": "8k"}))
        self.assertEqual((c["video"]["music_volume"], c["video"]["shorts_count"], c["video"]["quality"]), (1.0, 0, "1080p"))
        self.assertEqual(len(fixes), 3)

    def test_graph_version_format(self):
        c, _ = S.validate(self._cfg(publish={"facebook_graph_version": "24"}))
        self.assertEqual(c["publish"]["facebook_graph_version"], "v24.0")


class CatalogTest(unittest.TestCase):
    def test_voice_and_locale_labels(self):
        self.assertEqual(catalog.voice_label("es-MX-JorgeNeural"), "Jorge")
        self.assertEqual(catalog.voice_label("en-US-AndrewMultilingualNeural"), "Andrew (multilingüe)")
        self.assertEqual(catalog.locale_label("es-CO"), "Colombia")

    def test_regions_are_youtube_codes(self):
        self.assertTrue(all(c == "" or (len(c) == 2 and c.isupper()) for c, _ in catalog.REGIONS))


class RedactTest(unittest.TestCase):
    def test_keys_never_logged(self):
        text = redact("https://x/search?regionCode=US&key=AIzaSyA1234567890abcdefghijklmnopqrst&alt=json")
        self.assertNotIn("AIzaSy", text)
        self.assertIn("key=***", text)



class ReadingInstructionTest(unittest.TestCase):
    """Gemini TTS traducía frases enteras con un estilo en español y un guion en inglés."""

    def test_preset_is_translated_and_locked(self):
        style = catalog.READING_STYLES[1][0]
        text = catalog.reading_instruction(style, "en")
        self.assertTrue(text.startswith("Speak only in English"))
        self.assertIn("mystery narrator", text)
        self.assertNotIn("narrador", text)

    def test_spanish_keeps_style(self):
        self.assertIn("narrador de misterio", catalog.reading_instruction(catalog.READING_STYLES[1][0], "es"))


class FacebookJsonTest(unittest.TestCase):
    def test_non_json_answer_is_explained(self):
        from unittest import mock
        from agente.publish import facebook
        r = mock.Mock(status_code=502)
        r.json.side_effect = ValueError("Expecting value")
        with self.assertRaisesRegex(RuntimeError, "error 502"):
            facebook._json(r, "subida")


if __name__ == "__main__":
    unittest.main()
