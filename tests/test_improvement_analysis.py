"""Regression checks for read-only analysis and seed-specific matched comparisons."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import analyze_3seeds
import compare_runs
import diagnose_overorder
from result_io import ResultError, collect_episodes, is_factor, paired_keys


class ImprovementAnalysisTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def episode(self, folder, condition="C0M0T2", seed=1, cost=100, objective="cost", q_base=10):
        path = self.root / folder / "episodes" / f"{condition}__{objective}__seed-{seed}"
        path.mkdir(parents=True, exist_ok=True)
        summary = {"complete": True, "condition": condition, "seed": seed, "objective": objective,
                   "demand_hash": f"seed-{seed}", "metrics": {
                       "status": "completed", "cost_per_period": cost,
                       "retailer_immediate_fill_rate": 0.9, "global_bullwhip": 1.2,
                       "periods_evaluated": 1, "evaluation_start": 31, "evaluation_end": 31}}
        (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        row = {"agent": 0, "Q_final": 100, "Q_base": q_base, "B": 0, "P_pre": 0}
        (path / "periods.json").write_text(json.dumps([row]), encoding="utf-8")
        return self.root / folder

    def test_A_without_base_is_not_labelled_as_an_increase(self):
        folder = self.episode("A-only", condition="A", q_base=None)
        original = {p: p.read_bytes() for p in folder.rglob("*.json")}
        out = io.StringIO()
        with redirect_stdout(out):
            diagnose_overorder.main([str(folder), "--seed", "1"])
        self.assertIn("A | 소매 | 기준주문량 없음: 1회", out.getvalue())
        self.assertNotIn("A | 소매 | 기준 대비 상향 조정", out.getvalue())
        self.assertEqual(original, {p: p.read_bytes() for p in folder.rglob("*.json")})

    def test_duplicate_and_objective_conflicts_are_rejected(self):
        first = self.episode("first")
        second = self.episode("second", cost=999)
        with self.assertRaisesRegex(ResultError, "두 폴더"):
            collect_episodes([first, second])
        other_objective = self.episode("other-objective", objective="bullwhip")
        with self.assertRaisesRegex(ResultError, "목적 불일치"):
            paired_keys(collect_episodes([first]), collect_episodes([other_objective]))
        with self.assertRaises(ResultError):
            collect_episodes([first], seeds=[4])
        for invalid in ["C4M0T0", "C0M5T0", "C0M0T9", "CxMyTz", "A"]:
            self.assertFalse(is_factor(invalid))
        self.assertTrue(is_factor("C3M4T4"))

    def test_seed_specific_opposite_effects_remain_separate(self):
        for seed, cost in [(1, 80), (4, 120)]:
            self.episode("baseline", seed=seed, cost=100)
            self.episode("variant", seed=seed, cost=cost)
        config = {"baseline": "기존", "seeds": [1, 4], "variants": {
            "기존": {"1": ["baseline"], "4": ["baseline"]},
            "개선": {"1": ["variant"], "4": ["variant"]}}}
        file = self.root / "config.json"
        file.write_text(json.dumps(config), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            analyze_3seeds.main(["--config", str(file)])
        seed1, seed4 = out.getvalue().split("========== seed 4 ==========")
        self.assertIn("대응 차이 중앙값 -20.000", seed1)
        self.assertIn("대응 차이 중앙값 20.000", seed4)
        self.assertNotIn("부호순위 p", out.getvalue())

    def test_missing_baseline_does_not_promote_a_variant(self):
        folder = self.episode("variant")
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as context:
            compare_runs.main(["--baseline", str(self.root / "missing"),
                               "--variant", f"개선={folder}", "--seed", "1"])
        self.assertEqual(context.exception.code, 2)
        self.assertIn("결과 폴더가 없습니다", error.getvalue())


if __name__ == "__main__":
    unittest.main()
