"""Ejecución diaria resistente: la consola puede desaparecer y un run cortado se reanuda solo."""
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agente import events, pipeline


class BrokenStream:
    def write(self, s):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")


class LogOrderTest(unittest.TestCase):
    def test_broken_console_does_not_kill_run(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(events, "RUNS_DIR", Path(d)), \
                mock.patch("sys.stdout", BrokenStream()):
            r = events.Run("r1")
            r.warn("el guion vino incompleto")  # antes: OSError y el run moría sin dejar rastro
            lines = (Path(d) / "r1" / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("el guion vino incompleto", lines)


class SafeTeeTest(unittest.TestCase):
    def test_writes_file_even_if_console_gone(self):
        f = io.StringIO()
        tee = pipeline._SafeTee(BrokenStream(), f)
        tee.write("hola\n")
        tee.flush()
        self.assertEqual(f.getvalue(), "hola\n")


class InterruptedRecentTest(unittest.TestCase):
    def _run(self, d, name, **st):
        (Path(d) / name).mkdir()
        (Path(d) / name / "run.json").write_text(json.dumps(st), encoding="utf-8")

    def test_finds_recent_dead_run_only(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as d, mock.patch("agente.paths.RUNS_DIR", Path(d)):
            self._run(d, "20261118-210002", status="running", pid=0, started=now - 3600, options={"publish": True})
            self._run(d, "20261118-100000", status="running", pid=0, started=now - 30 * 3600, options={})
            self._run(d, "20261118-220000", status="done", pid=0, started=now - 600, options={})
            self._run(d, "20261118-230000", status="running", pid=0, started=now - 60, options={"mode": "metrics"})
            self.assertEqual(pipeline._interrupted_recent(), "20261118-210002")

    def test_none_when_all_fine(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("agente.paths.RUNS_DIR", Path(d)):
            self._run(d, "20261118-210002", status="done", pid=0, started=time.time(), options={})
            self.assertIsNone(pipeline._interrupted_recent())


class DailyResumesTest(unittest.TestCase):
    def test_scheduled_run_resumes_interrupted(self):
        calls = {}
        with mock.patch.object(pipeline, "_interrupted_recent", return_value="20261118-210002"), \
                mock.patch.object(pipeline, "_acquire_lock"), mock.patch.object(pipeline, "_release_lock"), \
                mock.patch.object(pipeline, "_maybe_shutdown", side_effect=lambda rid: calls.setdefault("off", rid)), \
                mock.patch.object(pipeline, "resume", side_effect=lambda rid: calls.setdefault("resume", rid) and 0), \
                mock.patch.object(pipeline, "full_run", side_effect=AssertionError("no debía empezar otro run")), \
                mock.patch.object(pipeline, "_notify", side_effect=lambda rid, code: code):
            pipeline.main(["--run-id", "20261119-210000", "--scheduled"])
        self.assertEqual(calls["resume"], "20261118-210002")
        self.assertEqual(calls["off"], "20261118-210002")  # el apagado automático sigue valiendo al reanudar


if __name__ == "__main__":
    unittest.main()
