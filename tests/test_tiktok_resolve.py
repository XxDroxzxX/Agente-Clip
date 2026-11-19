"""Publicaciones de TikTok que quedaron sin id: se identifican por texto o por duración y hora."""
import unittest

from agente.publish.browser import tt_match


class TtMatchTest(unittest.TestCase):
    look = {"text": "True Crime Documentary: 911 Red Flags That Catch Killers", "duration": 300.5, "ts": 1795052400}

    def test_by_text(self):
        it = {"desc": "True Crime Documentary: 911 Red Flags That Catch Killers #truecrime", "duration": 1000}
        self.assertTrue(tt_match(it, self.look))
        self.assertFalse(tt_match({"desc": "Otro video distinto", "duration": 300867}, self.look))

    def test_empty_text_uses_duration_and_time(self):
        # TikTok publicó el largo sin texto: duración 300,867 s, hora cercana
        self.assertTrue(tt_match({"desc": "", "duration": 300867, "create_time": 1795052500}, self.look))
        self.assertFalse(tt_match({"desc": "", "duration": 57900, "create_time": 1795052500}, self.look))
        self.assertFalse(tt_match({"desc": "", "duration": 300867, "create_time": 1795052400 - 86400}, self.look))


if __name__ == "__main__":
    unittest.main()
