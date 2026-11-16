"""Hashtags: los más usados del nicho y siempre #parati."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import research  # noqa: E402
from agente.scriptgen import finalize_hashtags  # noqa: E402


class HashtagTest(unittest.TestCase):
    def test_parati_always(self):
        for lang in ("es", "en", "pt"):
            for short in (True, False):
                self.assertIn("#parati", finalize_hashtags(["#a"], [], lang, short))

    def test_shorts_only_in_shorts_and_fyp_for_english(self):
        self.assertIn("#shorts", finalize_hashtags([], [], "en", True))
        self.assertNotIn("#shorts", finalize_hashtags([], [], "en", False))
        self.assertIn("#fyp", finalize_hashtags([], [], "en", True))
        self.assertNotIn("#fyp", finalize_hashtags([], [], "es", True))

    def test_niche_tags_fill_and_no_duplicates(self):
        out = finalize_hashtags(["#Terror", "terror"], ["#terror", "#miedo"], "es", True)
        self.assertEqual([t.lower() for t in out].count("#terror"), 1)
        self.assertIn("#miedo", out)
        self.assertLessEqual(len(out), 8)

    def test_top_hashtags_weighted_and_generic_removed(self):
        videos = [{"views_per_day": 100000, "hashtags": ["scary", "shorts", "horror"]},
                  {"views_per_day": 10, "hashtags": ["creepy", "fyp"]},
                  {"views_per_day": 5000, "hashtags": ["Horror"]}]
        tags = research.top_hashtags(videos)
        self.assertEqual(tags[0].lower(), "#horror")
        self.assertNotIn("#shorts", [t.lower() for t in tags])
        self.assertNotIn("#fyp", [t.lower() for t in tags])


if __name__ == "__main__":
    unittest.main()
