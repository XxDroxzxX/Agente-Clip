"""Video largo en todas las redes, enlace desde los Shorts, capítulos y aprendizaje por video y formato."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from agente import learning, pipeline, scriptgen


def plan(chapters):
    return NS(scenes=[NS(chapter=c) for c in chapters])


class ChaptersTest(unittest.TestCase):
    def test_valid_chapters(self):
        out = scriptgen.chapters(plan(["Intro", "", "The case", "", "What it means"]), [8, 10, 20, 15, 30])
        self.assertEqual(out.splitlines(), ["0:00 Intro", "0:18 The case", "0:53 What it means"])

    def test_first_forced_to_zero(self):
        out = scriptgen.chapters(plan(["", "A", "B", "C"]), [5, 30, 30, 30])
        self.assertTrue(out.startswith("0:00 A"))

    def test_too_few_or_too_short_is_empty(self):
        self.assertEqual(scriptgen.chapters(plan(["Intro", "Only"]), [30, 30]), "")
        # capítulos de menos de 10 s se omiten; si quedan menos de 3, no hay capítulos
        self.assertEqual(scriptgen.chapters(plan(["A", "B", "C"]), [3, 3, 40]), "")


class HookStylesTest(unittest.TestCase):
    def test_distinct_per_video(self):
        with mock.patch.object(learning, "load_learning", return_value={"styles": {}}):
            out = learning.choose_hook_styles(["long", "short_1", "short_2"], 0.3)
        self.assertEqual(set(out), {"long", "short_1", "short_2"})
        self.assertEqual(len({s for s, _ in out.values()}), 3)
        self.assertTrue(all(s in learning.HOOK_STYLES for s, _ in out.values()))

    def test_exploits_best_when_known(self):
        stats = {s: {"n": 5, "mean": 0.0} for s in learning.HOOK_STYLES}
        stats["historia"]["mean"] = 0.9
        with mock.patch.object(learning, "load_learning", return_value={"styles": stats}), \
                mock.patch.object(learning.random, "random", return_value=0.99):
            out = learning.choose_hook_styles(["long"], 0.3)
        self.assertEqual(out["long"][0], "historia")

    def test_prompt_lists_each_video(self):
        cfg = {"content": {"niche": "x", "language": "en", "audience": "a"},
               "video": {"long_enabled": True, "long_minutes": 4, "shorts_count": 1}}
        with mock.patch.object(scriptgen, "top_own_titles", return_value=[]), \
                mock.patch.object(scriptgen, "insights", return_value=[]):
            p = scriptgen.build_prompt(cfg, {}, {"long": "historia", "short_1": "pregunta"})
        self.assertIn("Video largo: historia", p)
        self.assertIn("Short 1: pregunta", p)
        self.assertIn("CAPÍTULOS", p)


class FormatTest(unittest.TestCase):
    def test_fmt_from_old_records(self):
        self.assertEqual(learning.fmt({"item": "long"}), "long")
        self.assertEqual(learning.fmt({"item": "short_2"}), "short")
        self.assertEqual(learning.fmt({"item": "x", "format": "long"}), "long")

    def test_long_compared_only_with_long(self):
        hist = [{"platform": "youtube", "platform_id": "L", "item": "long", "hook_style": "historia"},
                {"platform": "youtube", "platform_id": "S1", "item": "short_1", "hook_style": "pregunta"},
                {"platform": "youtube", "platform_id": "S2", "item": "short_2", "hook_style": "pregunta"}]
        snaps = [{"platform": "youtube", "platform_id": "L", "views": 0, "likes": 0, "comments": 0, "age_hours": 50, "ts": 1},
                 {"platform": "youtube", "platform_id": "S1", "views": 100, "likes": 5, "comments": 0, "age_hours": 50, "ts": 1},
                 {"platform": "youtube", "platform_id": "S2", "views": 100, "likes": 5, "comments": 0, "age_hours": 50, "ts": 1}]
        with mock.patch.object(learning, "load_history", return_value=hist), \
                mock.patch.object(learning, "load_snapshots", return_value=snaps), \
                mock.patch.object(learning, "write_json"):
            res = learning.recompute(48)
        # el largo con 0 vistas no castiga a su gancho frente a los Shorts: es el único largo
        self.assertEqual(res["styles"]["historia"]["mean"], 0.0)


class LongUploadTest(unittest.TestCase):
    def run_with(self, uploads):
        return NS(state={"uploads": uploads})

    def test_finds_long_and_builds_youtube_url(self):
        r = self.run_with([{"item": "long", "platform": "youtube", "platform_id": "abc123DEF45", "title": "T"}])
        self.assertEqual(pipeline._long_upload(r, "youtube")["url"], "https://youtu.be/abc123DEF45")
        self.assertIsNone(pipeline._long_upload(r, "facebook"))

    def test_ignores_failed_or_unknown_ids(self):
        r = self.run_with([{"item": "long", "platform": "youtube", "platform_id": None},
                           {"item": "long", "platform": "tiktok", "platform_id": "tt-browser-123", "url": ""}])
        self.assertIsNone(pipeline._long_upload(r, "youtube"))
        self.assertIsNone(pipeline._long_upload(r, "tiktok"))


if __name__ == "__main__":
    unittest.main()
