"""Apagado automático: solo en la ejecución diaria y si el usuario lo activó (sin apagar nada de verdad)."""
from __future__ import annotations

import copy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import pipeline  # noqa: E402
from agente.settings import DEFAULTS  # noqa: E402


class ShutdownTest(unittest.TestCase):
    def _main(self, argv, enabled):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["general"]["shutdown_after"] = enabled
        with mock.patch.object(pipeline.S, "load", return_value=cfg), \
                mock.patch.object(pipeline, "_acquire_lock"), mock.patch.object(pipeline, "_release_lock"), \
                mock.patch.object(pipeline, "full_run", return_value=0), \
                mock.patch.object(pipeline, "metrics_only", return_value=0), \
                mock.patch.object(pipeline, "_notify", side_effect=lambda r, c: c), \
                mock.patch.object(pipeline, "Run"), \
                mock.patch.object(subprocess, "run") as run:
            pipeline.main(argv)
        return [c for c in run.call_args_list if c.args and c.args[0][0] == "shutdown"]

    def test_scheduled_and_enabled_shuts_down_with_margin(self):
        calls = self._main(["--run-id", "x", "--scheduled"], True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0][:3], ["shutdown", "/s", "/t"])

    def test_manual_run_never_shuts_down(self):
        self.assertEqual(self._main(["--run-id", "x"], True), [])

    def test_disabled_never_shuts_down(self):
        self.assertEqual(self._main(["--run-id", "x", "--scheduled"], False), [])



class PublishTimeTest(unittest.TestCase):
    def test_delay(self):
        from datetime import datetime
        base = datetime(2026, 11, 16, 15, 0).timestamp()
        self.assertEqual(pipeline.publish_delay(base, "19:00"), 4 * 3600)
        self.assertEqual(pipeline.publish_delay(base, "09:00"), 0)   # ya pasó: se publica enseguida
        self.assertEqual(pipeline.publish_delay(base, ""), 0)
        self.assertEqual(pipeline.publish_delay(base, "xx"), 0)


if __name__ == "__main__":
    unittest.main()
