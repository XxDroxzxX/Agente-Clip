"""Idea propia, «hacer otro como este» y calendario de publicaciones."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agente import scriptgen

CFG = {"content": {"niche": "historias", "language": "en", "audience": "a"},
       "video": {"long_enabled": True, "long_minutes": 3, "shorts_count": 2}}
REF = {"topic": "El faro", "angle": "misterio real", "titles": ["The Lighthouse", "Short A", "Short B"],
       "long_scenes": 12, "short_scenes": [5, 6], "hooks": {"long": "historia"}}


def prompt(**kw):
    with mock.patch.object(scriptgen, "top_own_titles", return_value=[]), \
            mock.patch.object(scriptgen, "insights", return_value=[]):
        return scriptgen.build_prompt(CFG, {}, "pregunta", **kw)


class PromptTest(unittest.TestCase):
    def test_idea_is_mandatory_topic(self):
        p = prompt(idea="the lighthouse that turned off every night in 1987")
        self.assertIn("TEMA OBLIGATORIO", p)
        self.assertIn("lighthouse that turned off", p)

    def test_reference_keeps_formula_new_topic(self):
        p = prompt(reference=REF)
        self.assertIn("VIDEO DE REFERENCIA", p)
        self.assertIn("The Lighthouse", p)
        self.assertIn("12 escenas", p)
        self.assertIn("tema NUEVO", p)

    def test_plain_run_unchanged(self):
        p = prompt()
        self.assertNotIn("TEMA OBLIGATORIO", p)
        self.assertNotIn("REFERENCIA", p)


class ServerTest(unittest.TestCase):
    def test_start_run_passes_idea_and_like(self):
        import app.server as srv
        calls = []
        with tempfile.TemporaryDirectory() as d, mock.patch.object(srv, "RUNS_DIR", Path(d)), \
                mock.patch.object(srv, "_spawn", side_effect=lambda args, rid: calls.append(args)):
            (Path(d) / "ref1").mkdir()
            (Path(d) / "ref1" / "script.json").write_text("{}", encoding="utf-8")
            srv.start_run({"publish": False, "idea": "  mi idea  "})
            srv.start_run({"like": "ref1"})
            self.assertIn("--idea", calls[0])
            self.assertEqual(calls[0][calls[0].index("--idea") + 1], "mi idea")
            self.assertEqual(calls[1][calls[1].index("--like") + 1], "ref1")
            with self.assertRaises(srv.HTTPException):
                srv.start_run({"like": "no-existe"})

    def test_calendar_groups_by_day(self):
        import app.server as srv
        from datetime import datetime
        t = datetime(2026, 11, 18, 20, 39).timestamp()
        hist = [{"platform": "youtube", "platform_id": "a", "item": "long", "title": "T", "url": "u",
                 "run_id": "r", "published_at": t},
                {"platform": "tiktok", "platform_id": "b", "item": "short_1", "title": "S", "run_id": "r",
                 "published_at": datetime(2026, 12, 1).timestamp()}]
        with mock.patch.object(srv.learning, "load_history", return_value=hist), \
                mock.patch.object(srv.learning, "load_snapshots", return_value=[
                    {"platform": "youtube", "platform_id": "a", "views": 7, "ts": 1}]), \
                mock.patch.object(srv, "get_schedule", return_value={"enabled": False}):
            c = srv.calendar(2026, 11)
        self.assertEqual(list(c["days"]), [18])
        video = c["days"][18][0]  # agrupado por video: sus publicaciones van dentro
        self.assertEqual(video["format"], "long")
        self.assertEqual(video["time"], "20:39")
        self.assertEqual(video["posts"], [{"platform": "youtube", "url": "u", "views": 7}])
        self.assertEqual(c["days_in_month"], 30)
        with self.assertRaises(srv.HTTPException):
            srv.calendar(2026, 13)


class ReferenceTest(unittest.TestCase):
    def test_reference_from_run(self):
        from agente import pipeline
        pkg = {"topic": "El faro", "angle": "a", "broll_queries": [],
               "long_video": {"title": "L", "description": "d", "hashtags": [], "scenes": [
                   {"narration": "n", "visual_query": "q", "visual_prompt": "p"}] * 3},
               "shorts": [{"title": "S1", "description": "d", "hashtags": [], "scenes": [
                   {"narration": "n", "visual_query": "q", "visual_prompt": "p"}] * 2}]}
        with tempfile.TemporaryDirectory() as d, mock.patch("agente.paths.RUNS_DIR", Path(d)):
            (Path(d) / "r1").mkdir()
            (Path(d) / "r1" / "script.json").write_text(json.dumps(pkg), encoding="utf-8")
            (Path(d) / "r1" / "run.json").write_text(json.dumps({"hook_styles": {"long": "historia"}}), encoding="utf-8")
            ref = pipeline._reference("r1")
            self.assertIsNone(pipeline._reference("nada"))
        self.assertEqual(ref["titles"], ["L", "S1"])
        self.assertEqual(ref["long_scenes"], 3)
        self.assertEqual(ref["short_scenes"], [2])
        self.assertEqual(ref["hooks"], {"long": "historia"})


if __name__ == "__main__":
    unittest.main()
