"""Arreglos del run 20261117: stock de ambos bancos, préstamo entre escenas, idioma de tendencias, director."""
import unittest

from agente.research import same_script
from agente.visuals import _borrow, _gather
from agente.vision import Verdict


class FakeSrc:
    def __init__(self, name, n):
        self.name, self.n = name, n

    def candidates(self, query, min_dur, k):
        return [f"{self.name}{i}" for i in range(min(k, self.n))]


class GatherTest(unittest.TestCase):
    def test_mixes_both_banks(self):
        out = _gather([FakeSrc("P", 10), FakeSrc("X", 10)], "q", 4, 6, lambda *a: None)
        self.assertEqual(len(out), 6)
        self.assertEqual(out[:4], ["P0", "X0", "P1", "X1"])

    def test_one_bank_short(self):
        out = _gather([FakeSrc("P", 1), FakeSrc("X", 10)], "q", 4, 4, lambda *a: None)
        self.assertIn("P0", out)
        self.assertGreaterEqual(len(out), 3)


class BorrowTest(unittest.TestCase):
    def test_takes_spare_from_neighbour(self):
        scenes = {0: ["a"], 1: ["b"], 2: ["c"]}
        seqs = {0: ["c0", "c0b"], 1: [], 2: ["c2"]}
        self.assertEqual(_borrow(scenes, seqs, 1), ["c0b"])
        self.assertEqual(seqs[0], ["c0"])

    def test_nothing_spare(self):
        scenes = {0: ["a"], 1: ["b"]}
        seqs = {0: ["c0"], 1: []}
        self.assertEqual(_borrow(scenes, seqs, 1), [])


class ScriptTest(unittest.TestCase):
    def test_latin_titles(self):
        self.assertTrue(same_script("The Dark Mystery of Henry Walsh 😨 | True Crime", "en"))
        self.assertTrue(same_script("Historias de terror reales", "es"))

    def test_other_alphabets(self):
        self.assertFalse(same_script("ജഗതിയും നടി ശോഭയും | Untold Mysteries", "en"))
        self.assertFalse(same_script("실제 사건 범인의 소름 돋는 한마디", "en"))
        self.assertTrue(same_script("실제 사건 범인의 소름 돋는 한마디", "ko"))


class VerdictTest(unittest.TestCase):
    def test_long_issue_is_cut_not_rejected(self):
        v = Verdict.model_validate_json('{"score": 8, "issue": "' + "x" * 500 + '", "better_prompt": ""}')
        self.assertEqual(v.score, 8)
        self.assertEqual(len(v.issue), 200)


if __name__ == "__main__":
    unittest.main()
