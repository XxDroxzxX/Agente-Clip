"""El guion incompleto (el modelo corta la respuesta) se pide de nuevo con otro modelo."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import scriptgen  # noqa: E402
from agente.settings import DEFAULTS  # noqa: E402


def _plan(words: int):
    return scriptgen.VideoPlan(title="t", description="d", hashtags=["#a"], visual_bible="",
                               scenes=[scriptgen.Scene(narration=" ".join(["w"] * words), visual_query="q",
                                                       visual_prompt="p")],
                               music=None, thumbnail_text="x")


def _pkg(shorts: int, long_words: int = 500):
    return scriptgen.ScriptPackage(topic="t", angle="a", long_video=_plan(long_words),
                                   shorts=[_plan(90) for _ in range(shorts)], broll_queries=[])


class FakeRun:
    def __init__(self, tmp):
        self.warnings, self.tmp = [], Path(tmp)

    def warn(self, m, s=None): self.warnings.append(m)
    def info(self, m, s=None): pass
    def step_progress(self, *a, **k): pass
    def path(self, *p): return self.tmp.joinpath(*p)


class RetryTest(unittest.TestCase):
    def _go(self, answers):
        import tempfile
        cfg = copy.deepcopy(DEFAULTS)
        cfg["llm"]["provider"] = "gemini"
        cfg["video"].update(shorts_count=2, long_enabled=True, long_minutes=3)
        models = []

        def fake(c, prompt):
            models.append(c["llm"]["gemini_model"])
            return answers.pop(0), "fake"

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(scriptgen.PROVIDERS, {"gemini": ("Gemini", fake)}), \
                mock.patch.object(scriptgen, "build_prompt", return_value="p"):
            run = FakeRun(tmp)
            try:
                pkg = scriptgen.generate(run, cfg, {}, "pregunta")
            except RuntimeError as e:
                pkg = e
        return pkg, models, run

    def test_incomplete_then_complete(self):
        pkg, models, run = self._go([_pkg(0, 80), _pkg(2)])
        self.assertEqual(len(pkg.shorts), 2)
        self.assertNotEqual(models[0], models[1])  # el reintento usa otro modelo de la cadena
        self.assertTrue(run.warnings)

    def test_no_shorts_after_retries_fails_clearly(self):
        pkg, models, _ = self._go([_pkg(0), _pkg(0), _pkg(0)])
        self.assertIsInstance(pkg, RuntimeError)
        self.assertEqual(len(models), 3)

    def test_complete_first_time_no_retry(self):
        pkg, models, _ = self._go([_pkg(2)])
        self.assertEqual(len(models), 1)


if __name__ == "__main__":
    unittest.main()
