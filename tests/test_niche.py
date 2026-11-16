"""Investigación de nicho: puntaje y conversión de la recomendación a configuración válida (sin red)."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import catalog, niche  # noqa: E402
from agente import settings as S  # noqa: E402


class NicheTest(unittest.TestCase):
    def test_score_rewards_room_for_new_channels(self):
        crowded = {"videos": 20, "views_per_day": 50000, "engagement_pct": 2, "opportunity": 0.5, "small_channels_pct": 5}
        open_ = {"videos": 20, "views_per_day": 5000, "engagement_pct": 2, "opportunity": 20, "small_channels_pct": 80}
        self.assertGreater(niche.score(open_), niche.score(crowded))
        self.assertEqual(niche.score({"videos": 0}), 0.0)

    def test_recommendation_becomes_valid_settings(self):
        rec = niche.Recommendation(niche="Misterios", verdict="recomendado", why="w", content_ideas=["a"], hook_styles=["historia"],
                                   reading_style=99, visual_style=1, visual_provider="pexels", shorts_count=9,
                                   long_enabled=True, long_minutes=1, voice_rate="+6%", music=True, tips=["t"])
        patch = niche.to_settings(rec, {"niche": "Misterios", "audience": "a", "query": "unsolved mysteries"}, "en", "US")
        self.assertEqual(patch["voice"]["gemini_style"], catalog.READING_STYLES[0][0])  # índice inválido → el primero
        self.assertEqual(patch["video"]["shorts_count"], 3)
        self.assertEqual(patch["video"]["long_minutes"], 3)
        self.assertTrue(patch["voice"]["name"].startswith("en-"))
        cfg = S._merge(copy.deepcopy(S.DEFAULTS), patch)
        _, fixes = S.validate(cfg)
        self.assertEqual(fixes, [])


if __name__ == "__main__":
    unittest.main()
