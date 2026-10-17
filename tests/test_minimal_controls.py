"""Offline causal-boundary and fail-fast tests; HTTP responses are local doubles."""
from copy import deepcopy
from http.client import IncompleteRead
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scm.config import APIConfig, SimulationConfig
from scm.engine import make_warmup
from scm.harness import Harness, InvalidOrderQuantity, _validate_unrepaired_order
from scm.provider import (Budget, EpisodeAborted, FatalAPIError, MockProvider,
                          OpenRouterProvider, RecoverableCallError)
from scm.registry import get_condition


class Response:
    status = 200

    def __init__(self, value, raw=False, tier="flex"):
        self.data = {"model": "google/gemini-2.5-flash-lite", "status": "completed",
                     "service_tier": tier, "output_text": value if raw else json.dumps(value),
                     "openrouter_metadata": {"endpoints": {"available": [
                         {"selected": True, "provider": "Google AI Studio"}]}},
                     "usage": {"input_tokens": 10, "output_tokens": 5,
                               "total_tokens": 15, "cost": .0000015}}

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.data).encode()


class MinimalControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = SimulationConfig(safety_stock=10, evaluation_periods=2)
        cls.warmup, cls.demands = make_warmup(cls.config, 201)

    def setup_decision(self, name, provider):
        env = self.warmup.clone()
        row = env.begin_agent(0, 31, self.demands[30])
        return env, row, Harness(self.config, get_condition(name), provider)

    def test_n0_and_g0_receive_identical_minimal_inputs_and_prompt(self):
        records = {}
        for name in ("A", "N0", "N0-G0"):
            provider = MockProvider()
            env, row, harness = self.setup_decision(name, provider)
            result = harness.decide(env, 0, row, {"must_not_be_seen": 999})
            self.assertEqual(len(provider.events), 1)
            self.assertEqual(provider.events[0]["task"], "order")
            self.assertIsNone(result["Q_base"])
            self.assertIsNone(result["forecast"])
            self.assertIsNone(result["outgoing_message"])
            records[name] = provider.events[0]
        a, n0, g0 = (records[key] for key in ("A", "N0", "N0-G0"))
        self.assertEqual(n0["instructions"], g0["instructions"])
        self.assertEqual(n0["payload"], g0["payload"])
        self.assertEqual(n0["payload"], {"C": a["payload"]["C"], "D": a["payload"]["D"]})
        self.assertIn("information_sources", a["payload"])
        self.assertEqual(set(n0["payload"]), {"C", "D"})
        self.assertNotIn("information_sources", n0["instructions"])
        self.assertNotEqual(a["instructions"], n0["instructions"])
        # These historic reference values belong to the shared warm-up, not a
        # newly computed forecast or tool call in either minimal condition.
        self.assertTrue(any(r["Q_base"] is not None for r in n0["payload"]["C"]["past_orders"]))
        self.assertEqual(g0["effective_max_retries"], 0)
        self.assertEqual(n0["effective_max_retries"], 1)

    def test_g0_requires_exact_finite_mathematical_integer_without_coercion(self):
        for value in (0, 10, 100, 10.0, 1e1, -0.0, 100.0):
            with self.subTest(accepted=value):
                self.assertIsNone(_validate_unrepaired_order({"order_quantity": value}, 100))
        for value in (10.5, math.nextafter(10.0, math.inf), math.nextafter(10.0, -math.inf),
                      1e-300, -1, -1.0, 101, 100.01, 10**1000,
                      "10", True, False, None, float("nan"), float("inf"), -float("inf")):
            with self.subTest(rejected=value):
                with self.assertRaises(InvalidOrderQuantity):
                    _validate_unrepaired_order({"order_quantity": value}, 100)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_g0_integral_json_number_spellings_commit_without_repair_and_keep_raw(self):
        for literal, expected, raw_type in (("0", 0, int), ("10", 10, int), ("100", 100, int),
                                           ("10.0", 10, float), ("1e1", 10, float),
                                           ("-0.0", 0, float), ("100.0", 100, float)):
            with self.subTest(literal=literal):
                provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
                env, row, harness = self.setup_decision("N0-G0", provider)
                raw_json = '{"order_quantity":' + literal + ',"rationale":"test"}'
                with patch("scm.provider.urlopen", return_value=Response(raw_json, raw=True)) as http, \
                     patch("scm.provider.time.sleep") as sleep, \
                     patch("scm.harness.normalize_order", side_effect=AssertionError("G0 cannot repair quantities")):
                    result = harness.decide(env, 0, row, None)
                self.assertEqual(http.call_count, 1)
                sleep.assert_not_called()
                self.assertEqual(result["Q_final"], expected)
                self.assertIs(type(result["Q_final"]), int)
                self.assertIs(type(result["Q_final_raw"]), raw_type)
                self.assertEqual(result["Q_final_raw"], expected)
                if literal == "-0.0":
                    self.assertEqual(math.copysign(1, result["Q_final_raw"]), -1)
                self.assertFalse(result["order_corrected"])
                self.assertEqual(result["correction_count"], 0)
                self.assertEqual(result["retry_count"], 0)
                self.assertEqual(result["fallback_count"], 0)
                self.assertEqual(provider.events[0]["raw_output"], raw_json)
                self.assertEqual(provider.events[0]["effective_max_retries"], 0)
                self.assertEqual(env.next_agent, 1)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_g0_first_failure_never_retries_falls_back_or_commits(self):
        cases = [
            (Response('{"order_quantity":', raw=True), "invalid_output"),
            (Response({"order_quantity": 10.5, "rationale": "test"}), "invalid_action"),
            (Response({"order_quantity": math.nextafter(10.0, math.inf), "rationale": "test"}), "invalid_action"),
            (Response({"order_quantity": 1e-300, "rationale": "test"}), "invalid_action"),
            (Response({"order_quantity": -1, "rationale": "test"}), "invalid_action"),
            (Response({"order_quantity": 101, "rationale": "test"}), "invalid_action"),
            (Response({"order_quantity": True, "rationale": "test"}), "invalid_output"),
            (Response({"order_quantity": "10", "rationale": "test"}), "invalid_output"),
            (Response({"order_quantity": float("nan"), "rationale": "test"}), "invalid_output"),
            (Response({"order_quantity": float("inf"), "rationale": "test"}), "invalid_output"),
            (Response({"order_quantity": -float("inf"), "rationale": "test"}), "invalid_output"),
            (TimeoutError("test timeout"), "api_error"),
            (IncompleteRead(b"partial", 20), "api_error"),
        ]
        for response, expected_kind in cases:
            with self.subTest(response=response, kind=expected_kind):
                provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
                env, row, harness = self.setup_decision("N0-G0", provider)
                snapshot = deepcopy(env.to_dict())
                with patch("scm.provider.urlopen", side_effect=[response]) as http, \
                     patch("scm.provider.time.sleep") as sleep:
                    with self.assertRaises(EpisodeAborted) as caught:
                        harness.decide(env, 0, row, None)
                self.assertEqual(caught.exception.failure_kind, expected_kind)
                self.assertEqual(http.call_count, 1)
                sleep.assert_not_called()
                self.assertEqual(len(provider.events), 1)
                self.assertEqual(provider.events[0]["effective_max_retries"], 0)
                self.assertFalse(provider.events[0]["success"])
                self.assertEqual(env.to_dict(), snapshot)
                self.assertEqual(env.next_agent, 0)
                self.assertEqual(env.period_completed, 30)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_n0_retains_normalization_retry_and_fallback(self):
        provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
        env, row, harness = self.setup_decision("N0", provider)
        with patch("scm.provider.urlopen", side_effect=[Response({}, raw=False),
                   Response({"order_quantity": 10.5, "rationale": "test"})]) as http:
            result = harness.decide(env, 0, row, None)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result["Q_final"], 11)
        self.assertEqual(result["retry_count"], 1)
        self.assertTrue(result["order_corrected"])
        provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
        env, row, harness = self.setup_decision("N0", provider)
        with patch("scm.provider.urlopen", side_effect=TimeoutError("test timeout")) as http:
            result = harness.decide(env, 0, row, None)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result["Q_final"], row["D"])
        self.assertEqual(result["fallback_count"], 1)
        self.assertTrue(result["order_fallback"])

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_g0_fatal_route_violation_is_not_scientific_abort(self):
        provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
        env, row, harness = self.setup_decision("N0-G0", provider)
        with patch("scm.provider.urlopen", return_value=Response(
                {"order_quantity": 10, "rationale": "test"}, tier="standard")) as http:
            with self.assertRaises(FatalAPIError):
                harness.decide(env, 0, row, None)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(env.next_agent, 0)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_incomplete_http_error_body_preserves_recoverable_vs_fatal_classification(self):
        class BrokenHTTPError(HTTPError):
            def read(self):
                raise IncompleteRead(b"partial", 20)
        for code, exception_type in ((429, EpisodeAborted), (401, FatalAPIError)):
            with self.subTest(code=code):
                provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), budget=Budget(1))
                env, row, harness = self.setup_decision("N0-G0", provider)
                error = BrokenHTTPError("https://example.invalid", code, "offline test", {}, None)
                with patch("scm.provider.urlopen", side_effect=error) as http:
                    with self.assertRaises(exception_type):
                        harness.decide(env, 0, row, None)
                self.assertEqual(http.call_count, 1)
                event = provider.events[0]
                self.assertEqual(event["http_status"], code)
                self.assertEqual(event["error_body_read_error_type"], "IncompleteRead")
                self.assertTrue(event["error"])
                self.assertEqual(event["fatal"], code == 401)
                self.assertEqual(env.next_agent, 0)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-placeholder"})
    def test_zero_retry_failed_journal_cannot_replay_another_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "api_calls.jsonl"
            schema = {"type": "object", "properties": {"q": {"type": "number"}},
                      "required": ["q"], "additionalProperties": False}
            provider = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), journal, Budget(1))
            with patch("scm.provider.urlopen", return_value=Response({})) as http:
                with self.assertRaises(RecoverableCallError):
                    provider.ask("order", "test", {}, schema, {}, max_retries_override=0)
                self.assertEqual(http.call_count, 1)
            restored = OpenRouterProvider(APIConfig(retry_backoff_seconds=0), journal, Budget(1))
            with patch("scm.provider.urlopen") as http:
                with self.assertRaises(RecoverableCallError):
                    restored.ask("order", "test", {}, schema, {}, max_retries_override=0)
                http.assert_not_called()
            # A changed policy cannot accidentally reuse a different call key.
            with patch("scm.provider.urlopen", return_value=Response({"q": 10})) as http:
                restored.ask("order", "test", {}, schema, {})
                self.assertEqual(http.call_count, 1)
            self.assertNotEqual(restored.events[0]["call_key"], restored.events[1]["call_key"])


if __name__ == "__main__":
    unittest.main()
