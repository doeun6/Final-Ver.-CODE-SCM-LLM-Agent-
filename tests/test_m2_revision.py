"""M2 rule regressions and the shared minimal baseline prompt, entirely offline."""

import unittest

from scm.config import ROLES, SimulationConfig
from scm.m2_validation import validate_m2_message
from scm import prompts


class M2RevisionTests(unittest.TestCase):
    def test_qualitative_current_evidence_and_audited_negative_action_are_allowed(self):
        examples = (
            "The retailer has no backlog. Its committed order replenishes current stock.",
            "The backlog is zero.",
            "The retailer's message indicates their inventory is sufficient, and their current "
            "demand is low. My own inventory is also low, but my backlog is zero. Given the low "
            "demand and my current inventory position, I will not place an order with the "
            "distributor at this time.",
            "Limited inventory is one of the wholesaler's reasons for replenishing.",
            "The factory's committed order limits excess stock; no downstream state was supplied.",
            "I will not place an order at this time because outstanding orders cover current needs.",
            "I will not place an order for additional inventory at this time.",
            "Given the low demand and my current inventory position, I will not place an order "
            "with the distributor at this time.",
            "The retailer reports that their inventory is sufficient and they have no new "
            "information. My current inventory is adequate, and there are no outstanding "
            "backlogs or unfulfilled orders. Therefore, I will not place an order with the "
            "distributor at this time.",
            "We will not place any orders this period because current stock is sufficient.",
            "The retailer will not place an order now because inventory is sufficient.",
            "The supplier's message reports shortages; the wholesaler's own state supports replenishment.",
            "No clear reason for the committed quantity is supported by the supplied evidence.",
            "The retailer placed the current order to cover expected demand next period.",
            "The wholesaler reduced the current order because existing inventory covers next period demand.",
            "We place the current order to meet next period demand.",
            "소매점에는 백로그가 없습니다. 이번에 확정한 주문은 부족한 재고를 보충합니다.",
            "재고 부족은 여러 이유 중 하나입니다. 현재 추가 발주를 하지 않았습니다.",
            "이번에는 주문하지 않겠습니다.",
            "현재 추가 발주를 안 하겠습니다.",
            "다음 기 수요를 감안해 현재 주문했습니다.",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertIsNone(validate_m2_message(text))

    def test_explicit_future_plans_and_advice_are_rejected(self):
        examples = (
            "I will order more next period.",
            "The retailer will order more.",
            "The wholesaler plans to increase orders.",
            "We are going to replenish stock.",
            "Next period the factory places another order.",
            "Next period the factory replenishes stock.",
            "Our orders will be increased next period.",
            "The factory's order will be placed tomorrow.",
            "Our orders are scheduled for next period.",
            "The factory places another order next period.",
            "I will not place an order next period.",
            "I will not place an order at this time, but we will order tomorrow.",
            "I will not place an order with the distributor at this time, but the wholesaler "
            "will place another order tomorrow.",
            "Given sufficient stock, I will not place an order with the distributor at this time; "
            "next period the factory replenishes stock.",
            "You should order more to clear your backlog.",
            "Please increase orders.",
            "다음 기에는 발주를 줄입니다.",
            "소매점은 추가 주문을 할 계획입니다.",
            "재고를 보충하겠습니다.",
            "추가 발주를 하세요.",
            "이번에는 주문하지 않겠습니다. 다음 기에는 발주를 줄입니다.",
            "현재 추가 발주를 안 하겠습니다. 내일 주문할 계획입니다.",
        )
        for text in examples:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, 'future action|future actions'):
                    validate_m2_message(text)

    def test_quantities_in_digits_and_words_are_rejected_without_rejecting_one_of(self):
        examples = (
            "Inventory is 12.", "I ordered ten units.", "Inventory = ten.",
            "Our order quantity is twenty five.", "Two orders remain outstanding.",
            "We ordered one additional unit.", "The order is half the current demand.",
            "재고는 열 개입니다.", "두 개를 발주했습니다.", "발주량은 십 단위입니다.",
        )
        for text in examples:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, 'numeric quantities'):
                    validate_m2_message(text)

    def test_current_absence_equivalents_have_the_same_acceptance(self):
        # These are representations of the same categorical state, not a way
        # to smuggle positive quantities or future/statistical numeric values.
        examples = (
            "We have no backlog.", "Our backlog is zero.", "Our backlog is 0.",
            "Our backlog is 0.0.", "There is zero backlog.",
            "Our inventory is 0 units; the retailer has no backlog.",
            "Our outstanding orders are zero.", "We placed no order.",
            "Our current order is zero.", "Our committed order quantity is 0.",
            "We placed zero orders.", "I ordered zero units.",
            "Our current order is 0 because expected demand is low.",
            "현재 백로그는 없습니다.", "현재 백로그는 영입니다.", "현재 백로그는 0입니다.",
            "현재 재고는 0개입니다.", "현재 확정 주문량은 0입니다.",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertIsNone(validate_m2_message(text))

    def test_zero_exception_does_not_exempt_statistics_future_values_or_metadata(self):
        examples = (
            "The mean backlog is zero.", "The average inventory is 0.",
            "The standard deviation is zero.", "The minimum backlog is zero.",
            "The maximum inventory is 0.", "Forecast demand is zero.",
            "Expected demand is 0.", "Next period's order is zero.",
            "Our planned order is 0.", "Our order will be 0 next period.",
            "Plan: 0.", "Source 0 reports no backlog.", "0: no backlog.",
            "The backlog is 0.5.", "The backlog is 10.",
            "The backlog is zero and inventory is ten.",
            "평균 백로그는 0입니다.", "다음 기 발주량은 0입니다.",
            "백로그는 0.5개입니다.", "표준편차는 영 개입니다.",
        )
        for text in examples:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'numeric quantities'):
                validate_m2_message(text)

    def test_r3_pilot_current_absence_adverb_and_relative_clause_regressions(self):
        # Exact R3 responses: C0M2T2 retailer t39 and C0M2T4 wholesaler t36.
        # Acceptance only fixes the quantity gate, not all semantic claims.
        for text in (
            "My current order addresses a recent increase in customer demand, as my backlog "
            "is currently zero and my inventory is low.",
            "The committed order addresses a low on-hand inventory, which is currently zero. "
            "This order also accounts for a recent increase in customer demand.",
            "My backlog is now 0.", "My inventory currently is zero.",
            "My inventory, which is now at 0 units, is absent.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(validate_m2_message(text))

    def test_adverb_relative_clause_fix_keeps_numeric_and_time_boundaries(self):
        for text in (
            "Mean inventory, which is currently zero, explains the order.",
            "Forecast inventory, which is currently zero, explains the order.",
            "Next period's inventory, which is currently zero, explains the order.",
            "My inventory, which is currently zero next period, explains the order.",
            "My inventory is currently -0.", "My inventory is currently -1.",
            "My backlog is currently 0.5.", "My inventory, which is currently 0.5, is low.",
            "The mean backlog is currently zero.",
            # Exact R3 positive-quantity failures must still be rejected.
            "The distributor's current order addresses a backlog of 15 units owed to the "
            "wholesaler. This order also aims to replenish the distributor's inventory, "
            "which is currently at 0 units.",
            "The distributor's current order addresses a backlog of 15 units to the wholesaler, "
            "as the distributor's inventory is currently zero.",
            "The committed order addresses the retailer's low on-hand inventory, which is "
            "currently nine units. This order also accounts for the retailer's outstanding "
            "unfulfilled obligations to the external customer, which are zero.",
            "The committed order addresses a low on-hand inventory position, which is currently "
            "9 units. This order also accounts for a backlog of 0 units.",
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'numeric quantities'):
                validate_m2_message(text)

    def test_current_action_vs_future_action_minimal_pairs(self):
        pairs = (
            ("I will place the current order now because stock is low.",
             "I will place the current order tomorrow because stock is low."),
            ("I'll order now because stock is low.", "I'll order tomorrow because stock is low."),
            ("We’ll order this period because inventory is low.", "We’ll order next period."),
            ("We will proceed with our committed order now.", "We will proceed with our order next period."),
            ("The order will be submitted now.", "The order will be submitted tomorrow."),
            ("The order is submitted now.", "The order is submitted tomorrow."),
            ("I placed the current order to meet expected demand next period.",
             "I plan on ordering next period to meet demand."),
            ("현재 주문을 하겠습니다.", "내일 주문을 하겠습니다."),
            ("이번 기에는 추가 발주를 하지 않겠습니다.", "다음 기에는 추가 발주를 하지 않겠습니다."),
            ("주문은 현재 제출되었습니다.", "주문은 다음 기에 제출될 예정입니다."),
        )
        for current, future in pairs:
            with self.subTest(current=current):
                self.assertIsNone(validate_m2_message(current))
            with self.subTest(future=future), self.assertRaisesRegex(ValueError, 'future action'):
                validate_m2_message(future)

    def test_current_clause_does_not_hide_other_actions_or_advice(self):
        examples = (
            "I will place the current order now and tomorrow.",
            "I will place the current order now, but I'll order tomorrow as well.",
            "The order will be submitted now; the next order is submitted tomorrow.",
            "We will proceed with our current order now. I plan on ordering tomorrow.",
            "Our backlog is zero. Please increase orders.",
            "You should place your order now.", "Orders should be increased now.",
            "Consider ordering more.", "발주량을 늘려 주세요.",
            "현재 주문을 하겠습니다. 다음 기에는 발주를 줄입니다.",
        )
        for text in examples:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'future action'):
                validate_m2_message(text)

    def test_lexical_acceptance_does_not_claim_fact_or_ownership_validation(self):
        # The gate has no state or source inputs: each claim below passes its
        # lexical rules even when the assertion is false for a particular run.
        # Runtime acceptance must therefore never be counted as semantic truth.
        for text in (
            "The wholesaler has a large backlog; this explains its committed order.",
            "The wholesaler has no backlog; this explains its committed order.",
            "The retailer has high inventory.",
            "The factory has high inventory.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(validate_m2_message(text))

    def test_empty_or_nontext_messages_are_rejected(self):
        for value in ('', '  ', None, 12):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'nonblank'):
                validate_m2_message(value)

    def test_prompt_targets_observed_current_reasons_and_preserves_m4_instruction(self):
        message = prompts.message_instructions('wholesaler', 'M2', 100)
        self.assertIn('CURRENT COMMITTED order', message)
        self.assertIn('one or two relevant reasons', message)
        self.assertIn('not a reconstruction', message)
        self.assertIn('acknowledge that limitation', message)
        self.assertIn('present or completed-action', message)
        self.assertIn("'no backlog', 'backlog is zero' and 'backlog is 0'", message)
        self.assertIn('uncertain expectations', message)
        self.assertIn('does not allow numeric statistics', message)
        self.assertNotIn('Distinguish observation, interpretation and intention.', message)
        self.assertIn('Distinguish observation, interpretation and intention.',
                      prompts.message_instructions('wholesaler', 'M4', 100))
        self.assertIn('planning_evidence', prompts.message_instructions('wholesaler', 'M3', 100))


class MinimalPromptTests(unittest.TestCase):
    def test_essential_interface_without_engineered_semantic_guidance(self):
        config = SimulationConfig()
        for role in ROLES:
            with self.subTest(role=role):
                message = prompts.minimal_order_instructions(role, 'cost', config)
                self.assertIn(f'You are the {role}', message)
                self.assertIn('Current arrivals and shipments have finished', message)
                self.assertIn('I is inventory remaining', message)
                self.assertIn('B is unfilled demand owed', message)
                self.assertIn('P_pre is your outstanding orders', message)
                self.assertIn('null Q_base means no support quantity', message)
                self.assertIn(prompts.objective_instructions('cost', config), message)
                self.assertIn('order_quantity', message)
                self.assertIn('rationale', message)
                self.assertIn('must be an integer between 0 and 100', message)
                for removed in ('information_sources', 'source_path', 'Never substitute',
                                'never describe', 'inventory position', 'order-up-to',
                                'Integrate these three', 'Match each claim', 'reconsider',
                                'rounds', 'clips', 'rounding'):
                    self.assertNotIn(removed, message)


if __name__ == '__main__':
    unittest.main()
