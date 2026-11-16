"""Personaje consistente (Nano Banana) y Veo, con dobles de prueba (sin red ni costo)."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import gemini_media, visuals  # noqa: E402
from agente.settings import DEFAULTS  # noqa: E402


class FakeAI:
    segment = 5.0

    def __init__(self):
        self.calls = []

    def generate(self, prompt, start, dest, log, seconds=None):
        self.calls.append((prompt, start))
        dest.write_bytes(b"v")
        return dest

    def release(self):
        pass


def _run_ffmpeg(args, cwd=None, **k):
    (Path(cwd or ".") / str(args[-1])).write_bytes(b"x")


class CharacterTest(unittest.TestCase):
    def test_reference_once_and_keyframes_from_it(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["video"].update(visual_provider="comfyui", comfy_max_shots=0, comfy_keyframes=False, comfy_director=False)
        shots = [visuals.Shot(scene=s, duration=4.0, query="q", prompt=f"p{s}", bible="a man in a grey hoodie",
                              needs_ai=True) for s in range(3)]
        fake = FakeAI()
        made = []

        def sheet(bible, out, aspect, style=""):
            made.append(("sheet", bible, aspect))
            out.write_bytes(b"png")
            return out

        def key(prompt, ref, out, aspect):
            made.append(("key", prompt, ref.name))
            out.write_bytes(b"png")
            return out

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(visuals, "stock_sources", return_value=[]), \
                mock.patch.object(visuals, "ai_provider", return_value=fake), \
                mock.patch.object(visuals.S, "get_secret", return_value="clave-falsa"), \
                mock.patch.object(gemini_media, "character_sheet", side_effect=sheet), \
                mock.patch.object(gemini_media, "scene_keyframe", side_effect=key), \
                mock.patch.object(visuals.ffmpeg, "run", side_effect=_run_ffmpeg):
            visuals.fetch_for_item(shots, True, 1080, cfg, True, Path(tmp), lambda *a: None, lambda p: None)
        self.assertEqual([m[0] for m in made].count("sheet"), 1)            # una referencia por video
        self.assertEqual(made[0][2], "9:16")
        keys = [m for m in made if m[0] == "key"]
        self.assertEqual(len(keys), 3)                                       # una imagen clave por escena
        self.assertTrue(all(k[2] == "character.png" for k in keys))          # todas desde la misma referencia
        self.assertTrue(all(start is not None for _, start in fake.calls))   # y se animan desde esa imagen


class VeoTest(unittest.TestCase):
    def test_picks_fast_model_and_valid_duration(self):
        models = {"image": [], "video": ["veo-3.1-generate-preview", "veo-3.1-fast-generate-preview"]}
        self.assertEqual(gemini_media.video_model(copy.deepcopy(DEFAULTS), models), "veo-3.1-fast-generate-preview")
        cfg = copy.deepcopy(DEFAULTS)
        cfg["video"]["veo_model"] = "veo-3.1-generate-preview"
        self.assertEqual(gemini_media.video_model(cfg, models), "veo-3.1-generate-preview")
        self.assertEqual(next(d for d in gemini_media.VeoVideo.DURATIONS if d >= 4.6 - 0.05), 6)

    def test_quota_error_is_explained(self):
        r = mock.Mock(status_code=429, text="")
        r.json.return_value = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}
        self.assertIn("más tarde", str(gemini_media._explain(r, "Nano Banana")))
        r.json.return_value = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota", "details": [
            {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
        self.assertIn("plan gratuito de la API", str(gemini_media._explain(r, "Nano Banana")))



class ChainStartsTest(unittest.TestCase):
    def test_only_shots_that_start_a_chain(self):
        shots = [visuals.Shot(scene=s, duration=4, query="q", prompt="p") for s in (0, 0, 1, 1, 2)]
        ai_idx = {id(shots[i]): i for i in (0, 1, 2, 3)}       # la toma 4 va con stock
        starts = visuals._chain_starts(shots, ai_idx, by_scene=True)
        self.assertEqual([shots.index(s) for s in starts], [0, 2])
        self.assertEqual([shots.index(s) for s in visuals._chain_starts(shots, ai_idx, by_scene=False)], [0])


if __name__ == "__main__":
    unittest.main()
