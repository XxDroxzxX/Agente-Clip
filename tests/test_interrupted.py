"""Runs interrumpidos (p. ej. se apagó el PC): se pueden reanudar y no se marcan «en curso» al solo leerlos."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agente import comfyui, events, pipeline
from agente.util import pid_alive


class RunClaimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(events, "RUNS_DIR", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _finished_run(self):
        r = events.Run("r1")
        r.finish("done")
        return Path(self.tmp.name) / "r1" / "run.json"

    def test_open_without_claim_keeps_status(self):
        f = self._finished_run()
        events.Run("r1", create=False).info("aviso final")  # lo que hacían el aviso y el apagado automático
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["status"], "done")

    def test_claim_marks_running_with_pid_since(self):
        f = self._finished_run()
        events.Run("r1", create=False, claim=True)
        st = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(st["status"], "running")
        self.assertEqual(st["pid"], os.getpid())
        self.assertGreater(st["pid_since"], st["started"] - 1)


class PidTest(unittest.TestCase):
    def test_own_process(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertTrue(pid_alive(os.getpid(), since=time.time()))

    def test_reused_pid_after_reboot(self):
        # nuestro run «empezó» hace un día: un proceso con ese pid nacido hoy no es el nuestro
        if os.name == "nt":
            self.assertFalse(pid_alive(os.getpid(), since=time.time() - 86400))

    def test_dead(self):
        self.assertFalse(pid_alive(0))


class ServerResumeTest(unittest.TestCase):
    def test_running_with_dead_process_is_interrupted(self):
        import app.server as srv
        st = {"status": "running", "pid": 0, "started": time.time()}
        self.assertTrue(srv._interrupted(st))
        self.assertFalse(srv._interrupted({"status": "running", "pid": os.getpid(), "pid_since": time.time()}))
        self.assertFalse(srv._interrupted({"status": "done", "pid": 0}))


class ItemShotsTest(unittest.TestCase):
    def test_reuse_only_complete(self):
        with tempfile.TemporaryDirectory() as d:
            run = mock.Mock(dir=Path(d))
            (Path(d) / "long" / "shots").mkdir(parents=True)
            self.assertIsNone(pipeline._item_shots(run, "long"))
            (Path(d) / "long" / "shots.json").write_text(json.dumps(["long/shots/a.mp4"]), encoding="utf-8")
            self.assertIsNone(pipeline._item_shots(run, "long"))  # falta el archivo
            (Path(d) / "long" / "shots" / "a.mp4").write_bytes(b"x")
            self.assertEqual([p.name for p in pipeline._item_shots(run, "long")], ["a.mp4"])


class CoolDownTest(unittest.TestCase):
    def test_waits_when_hot(self):
        temps = iter([88.0, 80.0, 69.0])
        logs = []
        with mock.patch("agente.util.gpu_temperature", side_effect=lambda: next(temps)), \
                mock.patch.object(comfyui.time, "sleep"):
            comfyui.cool_down(logs.append)
        self.assertEqual(len(logs), 2)
        self.assertIn("88", logs[0])

    def test_no_wait_when_cool_or_unknown(self):
        logs = []
        with mock.patch("agente.util.gpu_temperature", return_value=60.0):
            comfyui.cool_down(logs.append)
        with mock.patch("agente.util.gpu_temperature", return_value=None):
            comfyui.cool_down(logs.append)
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
