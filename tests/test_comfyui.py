"""Pruebas sin red del proveedor ComfyUI y de la orquestación IA + stock."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import comfyui, visuals  # noqa: E402
from agente.settings import DEFAULTS  # noqa: E402


def _cfg(**video):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["video"].update(video)
    return cfg


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.ai = comfyui.ComfyVideo(_cfg(visual_provider="comfyui", ai_style="anime style"), portrait=True)

    def test_frames_are_4n_plus_1(self):
        self.assertEqual(comfyui.frames_for(5, 24), 121)
        for s in (1.3, 2.7, 4.0, 6.1):
            self.assertEqual(comfyui.frames_for(s, 24) % 4, 1)

    def test_fill_keeps_numbers(self):
        out = comfyui.fill({"a": "{{w}}", "b": "x {{w}} y", "c": ["1", 0]}, {"w": 832})
        self.assertEqual(out, {"a": 832, "b": "x 832 y", "c": ["1", 0]})

    def test_text_to_video_drops_start_image(self):
        wf = self.ai.build("a red fox in the snow", None, 5, seed=7)
        self.assertNotIn("7", wf)  # LoadImage
        latent = next(n for n in wf.values() if n["class_type"] == "Wan22ImageToVideoLatent")
        self.assertNotIn("start_image", latent["inputs"])
        self.assertEqual((latent["inputs"]["width"], latent["inputs"]["height"]), (480, 832))  # vertical
        self.assertEqual(latent["inputs"]["length"], 121)
        prompt = next(n for n in wf.values() if n["_meta"]["title"] == "Prompt")["inputs"]["text"]
        self.assertEqual(prompt, "a red fox in the snow. anime style")
        self.assertNotIn("{{", str(wf))

    def test_image_to_video_keeps_start_image(self):
        wf = self.ai.build("p", "agente_clips/f.jpg", 3)
        self.assertEqual(wf["7"]["inputs"]["image"], "agente_clips/f.jpg")
        self.assertEqual(wf["8"]["inputs"]["start_image"], ["7", 0])
        self.assertIsInstance(wf["9"]["inputs"]["seed"], int)

    def test_errors_are_translated(self):
        missing_node = {"error": {"type": "invalid_prompt", "message": "Cannot execute because node UnetLoaderGGUF does not exist."}}
        self.assertIn("ComfyUI-GGUF", comfyui.explain_error(missing_node))
        missing_file = {"error": {"type": "prompt_outputs_failed_validation", "message": "x"},
                        "node_errors": {"1": {"class_type": "UnetLoaderGGUF", "errors": [{"message": "Value not in list",
                                        "details": "unet_name: 'Wan2.2-TI2V-5B-Q5_K_M.gguf' not in []"}]}}}
        self.assertIn("models/unet", comfyui.explain_error(missing_file))

    def test_find_video_in_outputs(self):
        out = {"12": {"images": [{"filename": "toma_00001_.mp4", "subfolder": "agente_clips", "type": "output"}],
                      "animated": [True]}}
        self.assertEqual(comfyui.ComfyVideo.find_video(out)["filename"], "toma_00001_.mp4")


class FakeAI:
    segment = 5.0

    def __init__(self, keyframes=False):
        self.calls, self.keyframes = [], []
        self.released = False
        if keyframes:
            self.keyframe = self._keyframe

    def generate(self, prompt, start, dest, log, seconds=None):
        self.calls.append((prompt, start is not None, round(seconds, 2)))
        dest.write_bytes(b"video")
        return dest

    def _keyframe(self, prompt, dest, log):
        self.keyframes.append(prompt)
        dest.write_bytes(b"png")
        return dest

    def release(self):
        self.released = True


class FakeDirector:
    min = 6

    def __init__(self, clips=(), images=()):
        self.clips, self.images = iter(clips), iter(images)

    def ok(self, v):
        return v is None or v.score >= self.min

    def clip(self, *a):
        return next(self.clips, None)

    def image(self, *a):
        return next(self.images, None)


def _fake_ffmpeg(calls):
    def run(args, cwd=None, **k):
        calls.append([str(a) for a in args])
        out = Path(cwd or ".") / str(args[-1])
        out.write_bytes(b"x")
    return run


class OrchestrationTest(unittest.TestCase):
    def _shots(self, n=5):
        return [visuals.Shot(scene=i, duration=4.0, query=f"q{i}", prompt=f"p{i}") for i in range(n)]

    def test_hook_only_uses_ai_and_chains(self):
        fake = FakeAI()
        shots = self._shots()
        cfg = _cfg(visual_provider="comfyui", comfy_max_shots=2, comfy_chain="all", comfy_director=False)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(visuals, "stock_sources", return_value=[]), \
                mock.patch.object(visuals, "ai_provider", return_value=fake), \
                mock.patch.object(visuals.ffmpeg, "run", side_effect=_fake_ffmpeg(runs := [])):
            visuals.fetch_for_item(shots, True, 1080, cfg, True, Path(tmp), lambda *a: None, lambda p: None)
            # segunda llamada («Reintentar»): reutiliza los archivos ya generados
            again = self._shots()
            visuals.fetch_for_item(again, True, 1080, cfg, True, Path(tmp), lambda *a: None, lambda p: None)
        self.assertEqual([c[:2] for c in fake.calls], [("p0", False), ("p1", True)])
        self.assertEqual([s.kind for s in shots], ["video", "video", "color", "color", "color"])
        self.assertEqual(shots[0].credit, "Generado con IA")
        self.assertTrue(fake.released)
        self.assertEqual(len(fake.calls), 2)
        # el enlace es el último cuadro exacto en PNG y la toma encadenada pierde su 1.er cuadro (repetido)
        self.assertTrue(any(a[-1].endswith(".png") and "-update" in a for a in runs))
        self.assertTrue(any("trim=start_frame=1,setpts=PTS-STARTPTS" in a for a in runs))

    def test_long_shot_is_split_in_segments(self):
        fake = FakeAI()
        shots = [visuals.Shot(scene=0, duration=9.0, query="q", prompt="p")]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(visuals, "stock_sources", return_value=[]), \
                mock.patch.object(visuals, "ai_provider", return_value=fake), \
                mock.patch.object(visuals.ffmpeg, "extract_frame", side_effect=lambda v, out, **k: out), \
                mock.patch.object(visuals.ffmpeg, "run"):
            visuals.fetch_for_item(shots, False, 1080, _cfg(visual_provider="comfyui", comfy_max_shots=0, comfy_director=False),
                                   True, Path(tmp), lambda *a: None, lambda p: None)
        self.assertEqual(fake.calls, [("p", False, 4.5), ("p", True, 4.5)])
        self.assertEqual(shots[0].source.name, "ai_000.mp4")

    def _run(self, shots, cfg, fake, judge=None):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(visuals, "stock_sources", return_value=[]), \
                mock.patch.object(visuals, "ai_provider", return_value=fake), \
                mock.patch.object(visuals, "_director", return_value=judge), \
                mock.patch.object(visuals.ffmpeg, "run", side_effect=_fake_ffmpeg([])):
            visuals.fetch_for_item(shots, True, 1080, cfg, True, Path(tmp), lambda *a: None, lambda p: None)

    def test_chain_restarts_on_new_scene(self):
        fake = FakeAI()
        shots = [visuals.Shot(scene=s, duration=4.0, query="q", prompt=f"p{n}", bible="a black dog")
                 for n, s in enumerate([0, 0, 1, 1])]
        self._run(shots, _cfg(visual_provider="comfyui", comfy_max_shots=0, comfy_chain="scene"), fake)
        self.assertEqual([c[1] for c in fake.calls], [False, True, False, True])
        self.assertEqual(fake.calls[0][0], "p0. a black dog")  # la ficha visual va en cada prompt
        self.assertEqual([s.chained for s in shots], [False, True, False, True])

    def test_director_regenerates_and_keeps_best(self):
        fake = FakeAI()
        shots = [visuals.Shot(scene=0, duration=4.0, query="q", prompt=f"p{n}", bible="a black dog") for n in range(2)]
        bad = mock.Mock(score=3, issue="no se ve el perro", better_prompt="A black dog barks")
        director = FakeDirector(clips=[None, bad, mock.Mock(score=8)])
        self._run(shots, _cfg(visual_provider="comfyui", comfy_max_shots=0), fake, director)
        # 2.a toma: encadenada, reprobada y regenerada sin cadena con el prompt corregido; la nueva es mejor
        self.assertEqual(fake.calls[1][:2], ("p1. a black dog", True))
        self.assertEqual(fake.calls[2][:2], ("A black dog barks. a black dog", False))
        self.assertFalse(shots[1].chained)

    def test_director_keeps_first_if_retry_is_worse(self):
        fake = FakeAI()
        shots = [visuals.Shot(scene=0, duration=4.0, query="q", prompt="p")]
        director = FakeDirector(clips=[mock.Mock(score=5, issue="x", better_prompt="b"), mock.Mock(score=2)])
        self._run(shots, _cfg(visual_provider="comfyui", comfy_max_shots=0), fake, director)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[1][0], "b")
        self.assertTrue(shots[0].chained is False)

    def test_keyframe_is_checked_before_animating(self):
        fake = FakeAI(keyframes=True)
        shots = [visuals.Shot(scene=s, duration=4.0, query="q", prompt=f"p{s}", bible="a black dog") for s in (0, 0, 1)]
        bad = mock.Mock(score=2, issue="sin perro", better_prompt="A black dog on a sofa")
        director = FakeDirector(images=[bad, None, None])
        self._run(shots, _cfg(visual_provider="comfyui", comfy_max_shots=0), fake, director)
        # escena 0: dos intentos de imagen clave, el 2.o con el prompt corregido; escena 1: uno
        self.assertEqual(fake.keyframes, ["p0. a black dog", "A black dog on a sofa. a black dog", "p1. a black dog"])
        # se anima desde la imagen clave (con el prompt aprobado); la 2.a toma sigue la cadena
        self.assertEqual([c[:2] for c in fake.calls], [("A black dog on a sofa. a black dog", True),
                                                       ("p0. a black dog", True), ("p1. a black dog", True)])
        self.assertEqual([s.chained for s in shots], [False, True, False])

    def test_fal_uses_ai_on_every_shot(self):
        self.assertEqual(visuals.ai_shot_ids(self._shots(), _cfg(visual_provider="fal", comfy_max_shots=2)),
                         [0, 1, 2, 3, 4])


class DirectorAnswerTest(unittest.TestCase):
    """Gemini a veces se repite sin fin y el JSON llega cortado: se pregunta otra vez o se rescata la nota."""
    BAD = '{\n  "score": 4,\n  "issue": "lugar ' + "y tétrica " * 300
    GOOD = '{"score": 4, "issue": "sin conductor", "better_prompt": "Close-up of the driver"}'

    def _judge(self, answers):
        from agente import gemini, vision
        with mock.patch.object(vision, "provider", return_value="gemini"), \
                mock.patch.object(gemini, "generate", side_effect=[(a, "m") for a in answers]):
            return vision.judge_shot(_cfg(), [], "n", "p", lambda *a: None)

    def test_retries_cut_answer(self):
        self.assertEqual(self._judge([self.BAD, self.GOOD]).better_prompt, "Close-up of the driver")

    def test_salvages_score(self):
        v = self._judge([self.BAD, self.BAD])
        self.assertEqual((v.score, v.better_prompt), (4, ""))

    def test_gives_up_without_score(self):
        self.assertIsNone(self._judge(["{", "{"]))


if __name__ == "__main__":
    unittest.main()
