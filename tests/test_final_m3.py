"""Combined V1/V2 planning and audit boundaries, without paid API calls."""

from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from scm.config import APIConfig, ROLES, SimulationConfig
from scm.engine import make_warmup
from scm.forecasting import forecast
from scm.harness import Harness, _validate_message, build_C, plan_schema
from scm.provider import Budget, MockProvider, OpenRouterProvider, RecoverableCallError, validate_schema
from scm.registry import get_condition


class PlansProvider(MockProvider):
    def __init__(self, plans=(13, 9)):
        super().__init__()
        self.plans = plans

    def ask(self, task, instructions, payload, schema, meta, validate=None):
        result = super().ask(task, instructions, payload, schema, meta, validate)
        if task == "order":
            result["rationale"] = "PRIVATE_ORDER_RATIONALE_DO_NOT_REINJECT"
            self.events[-1]["parsed_output"] = deepcopy(result)
        if task == "message" and meta["message_level"] == "M3":
            result = {"plan_t_plus_1": self.plans[0], "plan_t_plus_2": self.plans[1],
                      "planning_evidence": f"AUDIT_ONLY_{meta['role']}_{meta['t']}"}
            validate_schema(result, schema)
            validate(result)
            self.events[-1]["parsed_output"] = deepcopy(result)
        return result


class Response:
    status = 200

    def __init__(self, value):
        self.data = {"model": "google/gemini-2.5-flash-lite", "status": "completed",
                     "service_tier": "flex", "id": "offline-final-test",
                     "output_text": json.dumps(value),
                     "openrouter_metadata": {"endpoints": {"available": [
                         {"selected": True, "provider": "Google AI Studio"}]}},
                     "usage": {"input_tokens": 10, "output_tokens": 5,
                               "total_tokens": 15, "cost": 0.0000015}}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.data).encode()


class FinalM3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = SimulationConfig(evaluation_periods=2)
        cls.warmup, cls.demands = make_warmup(cls.config, 17)

    def test_planning_preserves_all_context_windows_and_adds_no_forecast_call(self):
        for level, window in (("C0", 10), ("C1", 20), ("C2", 5), ("C3", 10)):
            with self.subTest(level=level):
                env, provider = self.warmup.clone(), PlansProvider()
                row = env.begin_agent(0, 31, self.demands[30])
                authorized = build_C(level, env.agents[0].history, row)
                with patch("scm.harness.forecast", wraps=forecast) as forecast_call:
                    result = Harness(self.config, get_condition(level+"M3T2"), provider).decide(
                        env, 0, row, None)
                self.assertEqual(forecast_call.call_count, 1)
                self.assertEqual([event["task"] for event in provider.events], ["order", "message"])
                payload = provider.events[-1]["payload"]
                self.assertEqual(set(payload), {"C", "M", "Q_base", "Q_final", "P_post",
                                               "information_sources"})
                self.assertEqual(payload["C"], authorized)
                self.assertEqual(payload["C"]["window"], window)
                self.assertEqual(payload["P_post"], row["P_pre"]+result["Q_final"])
                self.assertNotIn("history_30", json.dumps(payload))
                self.assertNotIn("PRIVATE_ORDER_RATIONALE", json.dumps(payload))
                if level == "C3":
                    self.assertNotIn("states", payload["C"])
                    self.assertEqual(payload["C"]["order_window"], 9)
                else:
                    self.assertEqual(len(payload["C"]["states"]), window)
                    self.assertEqual(len(payload["C"]["past_orders"]), window-1)

    def test_evidence_and_rationale_never_reach_upstream_or_later_calls(self):
        for level in ("C0", "C3"):
            with self.subTest(level=level):
                env, provider = self.warmup.clone(), PlansProvider()
                harness = Harness(self.config, get_condition(level+"M3T3"), provider)
                for t in (31, 32):
                    received, incoming = None, self.demands[t-1]
                    for i in range(4):
                        row = env.begin_agent(i, t, incoming)
                        result = harness.decide(env, i, row, received)
                        received, incoming = result["outgoing_message"], result["Q_final"]
                        self.assertIn("PRIVATE_ORDER_RATIONALE", result["rationale"])
                        if i < 3:
                            self.assertEqual(received, {"plan_t_plus_1": 13, "plan_t_plus_2": 9})
                            self.assertEqual(result["planning_evidence"], f"AUDIT_ONLY_{ROLES[i]}_{t}")
                            self.assertEqual(env.agents[i].history[-1]["planning_evidence"],
                                             result["planning_evidence"])
                        else:
                            self.assertIsNone(received)
                            self.assertNotIn("planning_evidence", result)
                for event in provider.events:
                    serialized = json.dumps(event["payload"])
                    self.assertNotIn("AUDIT_ONLY", serialized)
                    self.assertNotIn("planning_evidence", serialized)
                    self.assertNotIn("PRIVATE_ORDER_RATIONALE", serialized)
                    if event["task"] in ("select", "order") and event["agent"] > 0:
                        self.assertEqual(event["payload"]["M"],
                                         {"plan_t_plus_1": 13, "plan_t_plus_2": 9})
                        fields = {item["source_path"]: item for item in
                                  event["payload"]["information_sources"]["fields"]}
                        for path, offset in (("M.plan_t_plus_1", 1), ("M.plan_t_plus_2", 2)):
                            self.assertEqual(fields[path]["owner_role"], ROLES[event["agent"]-1])
                            self.assertEqual(fields[path]["period"], event["t"]+offset)
                            self.assertEqual(fields[path]["factual_status"], "nonbinding_plan")
                # Two periods * (4 select + 4 forecast + 4 order + 3 message).
                self.assertEqual(len(provider.events), 30)
                self.assertEqual(sum(e["task"] == "message" for e in provider.events), 6)

    def test_valid_plan_quantities_are_not_forced_to_differ(self):
        for plans in ((0, 100), (13, 9), (23, 23)):
            with self.subTest(plans=plans):
                env, provider = self.warmup.clone(), PlansProvider(plans)
                row = env.begin_agent(0, 31, self.demands[30])
                result = Harness(self.config, get_condition("C0M3T2"), provider).decide(env, 0, row, None)
                self.assertEqual(result["outgoing_message"], dict(zip(
                    ("plan_t_plus_1", "plan_t_plus_2"), plans)))
        env, provider = self.warmup.clone(), MockProvider()
        row = env.begin_agent(0, 31, self.demands[30])
        result = Harness(self.config, get_condition("C0M3T2"), provider).decide(env, 0, row, None)
        self.assertEqual(list(result["outgoing_message"].values()), [result["Q_final"]]*2)

    def test_current_order_rationale_is_private_for_every_generated_message_level(self):
        for level in ("M2", "M3", "M4"):
            with self.subTest(level=level):
                env, provider = self.warmup.clone(), PlansProvider()
                row = env.begin_agent(0, 31, self.demands[30])
                result = Harness(self.config, get_condition("C0"+level+"T2"), provider).decide(
                    env, 0, row, None)
                self.assertIn("PRIVATE_ORDER_RATIONALE", result["rationale"])
                message_call = next(e for e in provider.events if e["task"] == "message")
                self.assertNotIn("rationale", message_call["payload"])
                self.assertNotIn("PRIVATE_ORDER_RATIONALE", json.dumps(message_call["payload"]))
                self.assertEqual(result["rationale_audit"]["use"], "research_only_not_model_input")

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_invalid_evidence_uses_only_the_existing_one_retry(self):
        for evidence in (None, " \n\t ", "x"*601, False):
            with self.subTest(evidence_type=type(evidence).__name__):
                candidate = {"plan_t_plus_1": 12, "plan_t_plus_2": 10}
                if evidence is not None:
                    candidate["planning_evidence"] = evidence
                provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
                with patch("scm.provider.urlopen", return_value=Response(candidate)) as transport:
                    with self.assertRaises(RecoverableCallError):
                        provider.ask("message", "offline validation", {}, plan_schema(100), {},
                                     validate=lambda value: _validate_message(value, "M3", 100))
                self.assertEqual(transport.call_count, 2)
                self.assertEqual([e["format_failure"] for e in provider.events], [True, True])

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_invalid_planning_evidence_cannot_undo_committed_order(self):
        env = self.warmup.clone()
        row = env.begin_agent(0, 31, self.demands[30])
        provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
        order = Response({"order_quantity": 42, "rationale": "Current decision only."})
        bad = Response({"plan_t_plus_1": 12, "plan_t_plus_2": 10, "planning_evidence": " "})
        with patch("scm.provider.urlopen", side_effect=[order, bad, bad]) as transport:
            result = Harness(self.config, get_condition("C0M3T2"), provider).decide(env, 0, row, None)
        self.assertEqual(transport.call_count, 3)
        self.assertEqual(result["Q_final"], 42)
        self.assertEqual(result["P_post"], row["P_pre"]+42)
        self.assertTrue(result["message_fallback"])
        self.assertIsNone(result["outgoing_message"])
        self.assertNotIn("planning_evidence", result)
        self.assertEqual(result["format_failure_count"], 2)
        self.assertEqual(result["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
