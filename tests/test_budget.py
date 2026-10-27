"""Unit tests for tt/budget.py worst_case_cost() / RuntimeBudget.

stdlib unittest only. Note on worst_case_cost: it iterates a set, so
when several models lack prices the reported one is nondeterministic —
these tests therefore use a single missing model, or assert set
membership, never a multi-missing order.
"""

import unittest

from tt.budget import BudgetExceeded, RuntimeBudget, worst_case_cost


class TestWorstCaseCost(unittest.TestCase):
    def test_single_missing_price_model_is_reported(self):
        total, missing = worst_case_cost(
            models=["unknown/model"],
            judge_models=[],
            synth_model="known/model",
            question="Is this a good idea?",
            max_tokens=500,
            prices={"known/model": {"input": 1.0, "output": 2.0}},
            free_set=set(),
        )
        self.assertIsNone(total)
        self.assertEqual(missing, "unknown/model")

    def test_free_suffix_model_costs_zero(self):
        total, missing = worst_case_cost(
            models=["some/model:free"],
            judge_models=[],
            synth_model="other/model:free",
            question="Is this a good idea?",
            max_tokens=500,
            prices={},
            free_set=set(),
        )
        self.assertIsNone(missing)
        self.assertEqual(total, 0.0)

    def test_free_set_model_without_suffix_costs_zero(self):
        total, missing = worst_case_cost(
            models=["some/model"],
            judge_models=[],
            synth_model="some/model",
            question="Is this a good idea?",
            max_tokens=500,
            prices={},
            free_set={"some/model"},
        )
        self.assertIsNone(missing)
        self.assertEqual(total, 0.0)

    def test_priced_models_produce_positive_cost(self):
        total, missing = worst_case_cost(
            models=["a/model"],
            judge_models=["j/model"],
            synth_model="s/model",
            question="x" * 400,
            max_tokens=500,
            prices={
                "a/model": {"input": 1.0, "output": 2.0},
                "j/model": {"input": 1.0, "output": 2.0},
                "s/model": {"input": 1.0, "output": 2.0},
            },
            free_set=set(),
        )
        self.assertIsNone(missing)
        self.assertGreater(total, 0.0)

    def test_missing_judge_model_is_reported(self):
        # Only one model lacks a price, so the reported id is deterministic.
        total, missing = worst_case_cost(
            models=["a/model"],
            judge_models=["unknown/judge"],
            synth_model="s/model",
            question="q?",
            max_tokens=500,
            prices={
                "a/model": {"input": 1.0, "output": 2.0},
                "s/model": {"input": 1.0, "output": 2.0},
            },
            free_set=set(),
        )
        self.assertIsNone(total)
        self.assertEqual(missing, "unknown/judge")


class TestRuntimeBudget(unittest.TestCase):
    def test_charge_accumulates_spend(self):
        budget = RuntimeBudget(10.0)
        self.assertAlmostEqual(budget.charge(0.4), 0.4)
        self.assertAlmostEqual(budget.charge(0.3), 0.7)
        self.assertAlmostEqual(budget.spent, 0.7)

    def test_default_hard_limit_ratio_is_1_1(self):
        budget = RuntimeBudget(10.0)
        self.assertAlmostEqual(budget.limit, 11.0)
        self.assertAlmostEqual(budget.budget, 10.0)

    def test_charge_exactly_at_limit_does_not_raise(self):
        budget = RuntimeBudget(10.0)  # limit 11.0
        self.assertAlmostEqual(budget.charge(11.0), 11.0)

    def test_charge_over_limit_raises_budget_exceeded(self):
        budget = RuntimeBudget(10.0)  # limit 11.0
        budget.charge(11.0)
        with self.assertRaises(BudgetExceeded):
            budget.charge(0.01)

    def test_single_charge_over_limit_raises(self):
        budget = RuntimeBudget(1.0)  # limit 1.1
        with self.assertRaises(BudgetExceeded):
            budget.charge(2.0)

    def test_custom_hard_limit_ratio(self):
        budget = RuntimeBudget(10.0, hard_limit_ratio=1.0)
        budget.charge(10.0)
        with self.assertRaises(BudgetExceeded):
            budget.charge(0.01)


if __name__ == "__main__":
    unittest.main()
