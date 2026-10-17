"""Terminal G0 failures preserve evidence without inventing completed outcomes."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scm.analysis import analyze, execution_outcomes, make_report
from scm.config import SimulationConfig
from scm.provider import FatalAPIError, MockProvider, RecoverableCallError
from scm.runner import run_batch
from status import completed_status


def fault_provider(t=31, agent=0, mode="recoverable"):
    class InjectedProvider(MockProvider):
        def ask(self, task, instructions, payload, schema, meta, validate=None, *, max_retries_override=None):
            if meta["condition"] == "N0-G0" and meta["t"] == t and meta["agent"] == agent:
                if max_retries_override != 0:
                    raise AssertionError("G0 must disable retries before calling the provider")
                if mode == "fatal":
                    raise FatalAPIError("Injected route/configuration failure")
                error_type, error, validation_error = "TimeoutError", "Injected timeout", None
                format_failure = mode == "invalid_action"
                if format_failure:
                    try:
                        validate({"order_quantity": 153, "rationale": "Invalid action fixture"})
                    except ValueError as exc:
                        validation_error = type(exc).__name__
                        error_type, error = "ValidationError", str(exc)
                    else:
                        raise AssertionError("G0 must reject rather than cap 153")
                self.events.append(dict(meta, task=task, attempt=0, effective_max_retries=0,
                                        success=False, fatal=False, format_failure=format_failure,
                                        error_type=error_type, error=error,
                                        validation_error_type=validation_error,
                                        reported_cost_usd=None, input_tokens=None, output_tokens=None,
                                        total_tokens=None, reasoning_tokens=None, latency_seconds=0.25,
                                        budget_charge_usd=0.002,
                                        raw_output='{"order_quantity":153}' if format_failure else None))
                raise RecoverableCallError(error)
            return super().ask(task, instructions, payload, schema, meta, validate,
                               max_retries_override=max_retries_override)
    return InjectedProvider


class EpisodeAbortTests(unittest.TestCase):
    def run_fault(self, directory, *, t=31, agent=0, mode="recoverable", names=None, seeds=None):
        with patch("scm.runner.MockProvider", fault_provider(t, agent, mode)), redirect_stdout(io.StringIO()):
            return run_batch(names or ["N0-G0"], seeds or [201], directory,
                             config=SimulationConfig(evaluation_periods=3, safety_stock=10), workers=2)

    def test_initial_failure_is_terminal_with_pending_snapshot_and_no_order_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_fault(directory)[0]
            folder = Path(directory)/"episodes/N0-G0__cost__seed-201"
            self.assertFalse(result["complete"])
            self.assertTrue(result["terminal"])
            self.assertEqual((result["status"], result["abort_count"], result["completion_rate"]),
                             ("aborted", 1, 0))
            self.assertEqual(result["metrics"], {})
            partial = result["partial_metrics"]
            self.assertFalse(partial["full_horizon_comparable"])
            self.assertEqual(partial["completed_evaluation_periods"], 0)
            self.assertEqual(partial["committed_agent_periods"], 0)
            self.assertEqual(partial["partial_realized_cost"], 0)
            self.assertEqual(partial["usage"]["api_calls"], 1)
            self.assertEqual(partial["usage"]["retry_count"], 0)
            self.assertIsNone(partial["usage"]["reported_cost_usd"])
            self.assertEqual(partial["budget_accounted_usd"], 0.002)
            abort = result["abort"]
            self.assertEqual((abort["failed_period"], abort["failed_role"], abort["failed_phase"]),
                             (31, "retailer", "order"))
            snapshot = json.loads((folder/"abort_snapshot.json").read_text(encoding="utf-8"))
            self.assertFalse(snapshot["resume_allowed"])
            pending = snapshot["environment"]["pending"]
            self.assertNotIn("Q_final", pending["row"])
            self.assertEqual(len(snapshot["environment"]["agents"][0]["history"]), 30)
            self.assertEqual(json.loads((folder/"partial_periods.json").read_text()), [])
            self.assertFalse((folder/"periods.json").exists())
            self.assertFalse((folder/".running.lock").exists())

    def test_abort_after_commits_excludes_warmup_and_keeps_failed_call(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_fault(directory, t=32, agent=2)[0]
            folder = Path(directory)/"episodes/N0-G0__cost__seed-201"
            rows = json.loads((folder/"partial_periods.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row["t"] >= 31 for row in rows))
            self.assertNotIn((32, 2), [(row["t"], row["agent"]) for row in rows])
            partial = result["partial_metrics"]
            self.assertEqual(partial["completed_evaluation_periods"], 1)
            self.assertEqual(partial["committed_agent_periods"], 6)
            self.assertEqual(partial["partial_realized_cost"], sum(row["cost"] for row in rows))
            self.assertEqual(partial["usage"]["api_calls"], 7)
            self.assertEqual(partial["usage"]["failed_attempt_count"], 1)
            self.assertEqual(partial["usage"]["retry_count"], 0)
            self.assertEqual(result["metrics"], {})
            events = json.loads((folder/"mock_calls.json").read_text(encoding="utf-8"))
            self.assertEqual(len(events), 7)
            self.assertFalse(events[-1]["success"])

    def test_invalid_quantity_aborts_before_commit_without_clamping(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_fault(directory, mode="invalid_action")[0]
            self.assertEqual(result["abort"]["failure_kind"], "invalid_action")
            self.assertEqual(result["partial_metrics"]["committed_agent_periods"], 0)
            self.assertEqual(result["partial_metrics"]["usage"]["format_failure_count"], 1)
            self.assertEqual(result["partial_metrics"]["usage"]["retry_count"], 0)

    def test_other_trials_continue_and_abort_rates_have_seed_denominators(self):
        with tempfile.TemporaryDirectory() as directory:
            results = self.run_fault(directory, names=["N0-G0", "N0"], seeds=[201, 202])
            self.assertEqual(len(results), 4)
            self.assertEqual(sum(r["complete"] for r in results), 2)
            status = json.loads((Path(directory)/"batch_status.json").read_text(encoding="utf-8"))
            self.assertTrue(status["all_trials_terminal"])
            self.assertFalse(status["complete"])
            self.assertEqual((status["completed"], status["aborted"], status["attempted"]), (2, 2, 4))
            self.assertEqual(status["unexpected_error_count"], 0)
            self.assertEqual(status["scientific_resolved_episodes"], 4)
            self.assertEqual(status["experiment_abort_rate"], 0.5)
            self.assertTrue((Path(directory)/"execution_outcomes.csv").exists())
            rows = {row["condition"]: row for row in status["condition_outcomes"]}
            self.assertEqual(rows["N0-G0"]["abort_rate"], 1)
            self.assertEqual(rows["N0-G0"]["completion_rate"], 0)
            self.assertEqual(rows["N0"]["completion_rate"], 1)
            self.assertEqual(rows["N0"]["attempted"], 2)
            for seed in (201, 202):
                pair = [r for r in results if r["seed"] == seed]
                self.assertEqual(pair[0]["warmup_hash"], pair[1]["warmup_hash"])
            self.assertEqual(len(json.loads((Path(directory)/"failures.json").read_text())), 2)
            read_status = completed_status(directory)
            self.assertEqual(read_status["aborted_episodes"], 2)
            self.assertEqual(read_status["completed_episodes"], 2)
            self.assertTrue(read_status["all_trials_terminal"])
            self.assertFalse(read_status["all_episodes_completed"])

    def test_resume_never_constructs_provider_for_terminal_aborted_result(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.run_fault(directory, t=32, agent=1)
            folder = Path(directory)/"episodes/N0-G0__cost__seed-201"
            before = (folder/"mock_calls.json").read_bytes()
            with patch("scm.runner.MockProvider", side_effect=AssertionError("Must not replay abort")), redirect_stdout(io.StringIO()):
                resumed = run_batch(["N0-G0"], [201], directory, resume=True,
                                    config=SimulationConfig(evaluation_periods=3, safety_stock=10), workers=2)
            self.assertEqual(first, resumed)
            self.assertEqual(before, (folder/"mock_calls.json").read_bytes())
            status = json.loads((Path(directory)/"batch_status.json").read_text())
            self.assertEqual(status["aborted"], 1)
            self.assertEqual(status["attempted"], 1)

    def test_fatal_route_or_configuration_error_stops_batch_not_scientific_abort(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "Batch incomplete"):
                self.run_fault(directory, mode="fatal")
            status = json.loads((Path(directory)/"batch_status.json").read_text())
            self.assertEqual(status["aborted"], 0)
            self.assertEqual(status["unexpected_error_count"], 1)
            self.assertEqual(status["scientific_resolved_episodes"], 0)
            self.assertIsNone(status["experiment_abort_rate"])
            self.assertFalse(status["terminal"])
            folder = Path(directory)/"episodes/N0-G0__cost__seed-201"
            self.assertFalse((folder/"abort.json").exists())
            self.assertFalse((folder/"summary.json").exists())
            self.assertEqual(json.loads((folder/"failure.json").read_text())["type"], "FatalAPIError")

    def test_scientific_abort_denominator_excludes_unexpected_errors_and_cancelled(self):
        completed = {"condition": "N0-G0", "seed": 1, "complete": True, "metrics": {}}
        aborted = {"condition": "N0-G0", "seed": 2, "complete": False, "status": "aborted", "metrics": {}}
        errors = [{"condition": "N0-G0", "seed": 3, "type": "FatalAPIError", "message": "Missing credentials"},
                  {"condition": "N0-G0", "seed": 4, "type": "CancelledError", "message": ""}]
        report = execution_outcomes([completed, aborted], conditions=["N0-G0"], seeds=[1, 2, 3, 4, 5], errors=errors)
        for row in (report["totals"], report["by_condition"][0]):
            self.assertEqual(row["attempted_outcome_denominator"], 3)
            self.assertEqual(row["scientific_resolved_episodes"], 2)
            self.assertAlmostEqual(row["abort_rate"], 1/3)
            self.assertEqual(row["experiment_abort_rate"], 0.5)
            self.assertEqual(row["experiment_completion_rate"], 0.5)
        self.assertEqual(report["by_condition"][0]["completion_rate_of_planned"], 0.2)

    def test_legacy_analysis_excludes_abort_and_withholds_inference(self):
        from tests.test_metrics import pilot_results
        data = deepcopy(pilot_results())
        failed = data[0]
        failed.update(status="aborted", complete=False, metrics={}, abort_count=1,
                      partial_metrics={"partial_realized_cost": 0, "completed_evaluation_periods": 0,
                                       "committed_agent_periods": 0, "usage": {"api_calls": 1, "retry_count": 0}},
                      abort={"failed_period": 31, "failed_role": "retailer", "failed_phase": "order", "reason": "Invalid JSON"})
        report = analyze(data)
        self.assertFalse(report["complete"])
        self.assertEqual(report["completed_executions"], 31)
        self.assertEqual(report["conditions"]["A"]["n"], 7)
        self.assertEqual(report["execution_outcomes"]["totals"]["aborted"], 1)
        self.assertTrue(all(x["p_value"] is None for x in report["primary_contrasts"]))
        self.assertIn("실패로 종료된 실행", make_report(report))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            execution_outcomes([failed, failed])


if __name__ == "__main__":
    unittest.main()
