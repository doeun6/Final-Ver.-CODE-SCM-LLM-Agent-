"""Information attribution regressions for the combined final harness.

These offline tests verify the delivered inputs and boundaries. They do not
claim that a live model will always obey the ownership instructions.
"""

from copy import deepcopy
import json
import unittest

from scm.config import ROLES, SimulationConfig
from scm import prompts
from scm.engine import make_warmup
from scm.harness import Harness, build_C
from scm.ownership import POST_ORDER, PRE_ORDER, build_information_sources
from scm.provider import MockProvider
from scm.registry import get_condition


def source_map(payload):
    return {item["source_path"]: item for item in payload["information_sources"]["fields"]}


class FinalOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = SimulationConfig(evaluation_periods=2)
        cls.warmup, cls.demands = make_warmup(cls.config, 17)

    def test_conflicting_self_and_downstream_values_keep_their_actual_owners(self):
        # Reproduce the reported reverse-attribution failure: self I=363 must
        # never acquire the downstream role, even when a downstream report exists.
        for i, role in enumerate(ROLES):
            with self.subTest(role=role):
                message = None if i == 0 else {
                    "t": 31, "sender": ROLES[i-1], "I": 7, "B": 4,
                    "P_post": 29, "D": 11, "D_mean_10": 9, "D_std_10": 2,
                }
                payload = {"C": {"current": {"t": 31, "I": 363, "B": 0,
                                              "P_pre": 17, "D": 23}},
                           "M": message, "Q_base": 0}
                original = deepcopy(payload)
                sources = build_information_sources(role, 31, "order", payload)
                self.assertEqual(payload, original, "Source labeling must not mutate evidence")
                fields = {item["source_path"]: item for item in sources["fields"]}
                for variable in ("I", "B", "P_pre", "D"):
                    self.assertEqual(fields["C.current."+variable]["owner_role"], role)
                    self.assertEqual(fields["C.current."+variable]["phase"], PRE_ORDER)
                self.assertEqual(fields["Q_base"]["owner_role"], role)
                if i:
                    for variable in ("I", "B", "P_post", "D", "D_mean_10", "D_std_10"):
                        self.assertEqual(fields["M."+variable]["owner_role"], ROLES[i-1])
                    self.assertEqual(fields["M.P_post"]["phase"], POST_ORDER)
                    self.assertNotEqual(fields["C.current.I"]["owner_role"],
                                        fields["M.I"]["owner_role"])
                else:
                    self.assertEqual(fields["M"]["availability"], "absent")
                    self.assertFalse(any(path.startswith("M.") for path in fields))
                # Ownership metadata identifies evidence; it must not duplicate
                # state values or manufacture an additional observation.
                self.assertNotIn("363", json.dumps(sources))
                self.assertFalse(any("value" in item for item in sources["fields"]))

    def test_c_level_windows_and_representations_survive_source_labeling(self):
        for level, window in (("C0", 10), ("C1", 20), ("C2", 5), ("C3", 10)):
            with self.subTest(level=level):
                env, provider = self.warmup.clone(), MockProvider()
                row = env.begin_agent(0, 31, self.demands[30])
                allowed = build_C(level, env.agents[0].history, row)
                Harness(self.config, get_condition(level+"M0T4"), provider).decide(env, 0, row, None)
                for event in provider.events:
                    payload = event["payload"]
                    self.assertEqual(payload["C"], allowed)
                    self.assertEqual(payload["C"]["window"], window)
                    self.assertNotIn("history_30", payload)
                    fields = source_map(payload)
                    self.assertEqual(fields["C"]["owner_role"], "retailer")
                    if level == "C3":
                        self.assertNotIn("states", payload["C"])
                        self.assertNotIn("past_orders", payload["C"])
                        self.assertEqual(fields["C.statistics"]["period_start"], 22)
                        self.assertEqual(fields["C.statistics"]["period_end"], 31)
                        self.assertEqual(fields["C.order_statistics"]["period_end"], 30)
                    else:
                        self.assertEqual(len(payload["C"]["states"]), window)
                        self.assertEqual(len(payload["C"]["past_orders"]), window-1)
                self.assertEqual([e["task"] for e in provider.events], ["select", "order"])

    def test_a_direct_order_has_no_m_forecast_or_reference_in_its_evidence(self):
        env, provider = self.warmup.clone(), MockProvider()
        row = env.begin_agent(0, 31, self.demands[30])
        result = Harness(self.config, get_condition("A"), provider).decide(
            env, 0, row, {"I": 99999})
        self.assertEqual(len(provider.events), 1)
        payload = provider.events[0]["payload"]
        self.assertEqual(set(payload), {"C", "D", "information_sources"})
        self.assertEqual(payload["D"], payload["C"]["current"]["D"])
        fields = source_map(payload)
        self.assertEqual(fields["D"]["owner_role"], "retailer")
        self.assertFalse(any(path == "M" or path.startswith("M.") for path in fields))
        self.assertNotIn("history_30", fields)
        self.assertNotIn("Q_base", fields)
        self.assertIsNone(result["Q_base"])
        self.assertNotIn("99999", json.dumps(payload))

    def test_forecast_metadata_contains_only_own_history_and_future_targets(self):
        env, provider = self.warmup.clone(), MockProvider()
        harness = Harness(self.config, get_condition("C0M2T1"), provider)
        incoming, received = self.demands[30], None
        for i, role in enumerate(ROLES):
            row = env.begin_agent(i, 31, incoming)
            result = harness.decide(env, i, row, received)
            incoming, received = result["Q_final"], result["outgoing_message"]
        forecasts = [event for event in provider.events if event["task"] == "forecast"]
        self.assertEqual(len(forecasts), 4)
        for event in forecasts:
            payload = event["payload"]
            self.assertEqual(len(payload["history_30"]), 30)
            self.assertNotIn("C", payload)
            self.assertNotIn("M", payload)
            fields = source_map(payload)
            self.assertEqual(set(fields), {"history_30", "targets"})
            self.assertEqual(fields["history_30"]["owner_role"], event["role"])
            self.assertEqual(fields["history_30"]["period_start"], 2)
            self.assertEqual(fields["history_30"]["period_end"], 31)
            self.assertEqual(fields["targets"]["target_periods"], [32, 33])

    def test_m1_post_order_pipeline_is_downstream_while_c_is_receivers_own(self):
        env, provider = self.warmup.clone(), MockProvider()
        harness = Harness(self.config, get_condition("C2M1T2"), provider)
        incoming, received = self.demands[30], None
        for i, role in enumerate(ROLES):
            before = deepcopy(received)
            row = env.begin_agent(i, 31, incoming)
            result = harness.decide(env, i, row, received)
            event = provider.events[-1]
            self.assertEqual(event["task"], "order")
            self.assertEqual(event["payload"]["M"], before)
            fields = source_map(event["payload"])
            self.assertEqual(fields["C.current.P_pre"]["owner_role"], role)
            if i:
                self.assertEqual(fields["M.P_post"]["owner_role"], ROLES[i-1])
                self.assertEqual(fields["M.P_post"]["phase"], POST_ORDER)
                self.assertEqual(fields["M.D_mean_10"]["period_start"], 22)
                self.assertEqual(fields["M.D_mean_10"]["period_end"], 31)
            if i < 3:
                self.assertEqual(result["outgoing_message"]["P_post"],
                                 row["P_pre"]+result["Q_final"])
            incoming, received = result["Q_final"], result["outgoing_message"]
        self.assertEqual(len(provider.events), 4, "M1 must not add an LLM message call")

    def test_message_stage_separates_own_post_order_p_from_received_m1_p(self):
        payload = {"C": {"current": {"t": 31, "I": 363, "P_pre": 17}},
                   "M": {"t": 31, "I": 7, "P_post": 29},
                   "Q_final": 12, "P_post": 29}
        fields = {item["source_path"]: item for item in
                  build_information_sources("wholesaler", 31, "message", payload)["fields"]}
        self.assertEqual(fields["P_post"]["owner_role"], "wholesaler")
        self.assertEqual(fields["P_post"]["phase"], POST_ORDER)
        self.assertEqual(fields["M.P_post"]["owner_role"], "retailer")
        self.assertEqual(fields["M.P_post"]["phase"], POST_ORDER)
        self.assertEqual(fields["C.current.P_pre"]["phase"], PRE_ORDER)

    def test_qualitative_message_is_report_not_measured_inventory_of_sender(self):
        text = "The retailer reports excess inventory; my own backlog has cleared."
        payload = {"M": text}
        information = build_information_sources("distributor", 31, "order", payload)
        self.assertEqual(payload, {"M": text})
        self.assertEqual(len(information["fields"]), 1)
        field = information["fields"][0]
        self.assertEqual(field["source_path"], "M")
        self.assertEqual(field["sender_role"], "wholesaler")
        self.assertIsNone(field["owner_role"])
        self.assertEqual(field["reported_owner"], "as_explicitly_attributed_in_text_or_unknown")
        self.assertEqual(field["factual_status"], "unverified_report")
        self.assertNotIn("M.I", json.dumps(information))

    def test_all_roles_receive_both_direction_guards_at_each_c_m_stage(self):
        for role in ROLES:
            texts = [prompts.selection_instructions(role),
                     prompts.order_instructions(role, "cost", self.config)]
            texts.extend(prompts.message_instructions(role, level, 100)
                         for level in ("M2", "M3", "M4"))
            for instructions in texts:
                with self.subTest(role=role, prefix=instructions[:80]):
                    self.assertIn("Never substitute or add downstream state into these local fields.",
                                  instructions)
                    self.assertIn("Never use your own C values as numerical evidence for a downstream state.",
                                  instructions)
            self.assertIn("actual source path", prompts.order_instructions(role, "cost", self.config))
            self.assertIn("information_sources.fields", prompts.stage_instructions(role, 31, "order"))


if __name__ == "__main__":
    unittest.main()
