"""Tests for the recurring five-minute runner loop without network calls."""
import subprocess
import unittest

import watch_loop as w


class RunnerLoopTests(unittest.TestCase):
    def test_minute_alignment(self):
        self.assertEqual(w.next_tick(100, 101), 400)
        self.assertEqual(w.next_tick(100, 399), 400)
        self.assertEqual(w.next_tick(100, 400), 700)
        self.assertEqual(w.next_tick(100, 725), 1000)

    def test_contains_both_modes(self):
        self.assertEqual(w.COMMANDS["retail"], ("retail_watch.py",))
        self.assertEqual(w.COMMANDS["promo"],
                         ("promo_watch.py", "catalog_watch.py", "dcinside_watch.py"))

    def test_retail_single_pass(self):
        calls = []
        def fake_runner(argv, timeout, check):
            calls.append(argv[-1])
            return subprocess.CompletedProcess(argv, 0)
        self.assertEqual(w.check_once("retail", fake_runner), [])
        self.assertEqual(calls, ["retail_watch.py"])

    def test_promo_independent_failure(self):
        calls = []
        def fake_runner(argv, timeout, check):
            calls.append(argv[-1])
            return subprocess.CompletedProcess(argv, 1 if "catalog" in argv[-1] else 0)
        self.assertEqual(len(w.check_once("promo", fake_runner)), 1)
        self.assertEqual(calls, ["promo_watch.py", "catalog_watch.py", "dcinside_watch.py"])


if __name__ == "__main__":
    unittest.main()
