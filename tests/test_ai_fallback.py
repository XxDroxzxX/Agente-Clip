"""Si una toma IA falla a medias, se usa lo ya generado (no un clip de stock sin revisar)."""
import tempfile
import unittest
from pathlib import Path

from agente.visuals import _ai_fallback


class AiFallbackTest(unittest.TestCase):
    def test_prefers_video_then_keyframe(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertIsNone(_ai_fallback(d, 1))
            (d / "key_001_0.png").write_bytes(b"x")
            self.assertEqual(_ai_fallback(d, 1).name, "key_001_0.png")
            (d / "ai_001_0.mp4").write_bytes(b"x")
            self.assertEqual(_ai_fallback(d, 1).name, "ai_001_0.mp4")
            self.assertIsNone(_ai_fallback(d, 2))

    def test_ignores_empty_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "ai_003_0.mp4").write_bytes(b"")
            self.assertIsNone(_ai_fallback(d, 3))


if __name__ == "__main__":
    unittest.main()
