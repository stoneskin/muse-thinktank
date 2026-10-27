"""Unit tests for tt/budget.py worst_case_cost() / RuntimeBudget.

stdlib unittest only. Note on worst_case_cost: it iterates a set, so
when several models lack prices the reported one is nondeterministic —
these tests therefore use a single missing model, or assert set
membership, never a multi-missing order.
"""

import unittest

from tt.budget import (BudgetExceeded, RuntimeBudget, worst_case_cost,
                       load_prices, effective_max_tokens, synth_cap,
                       completion_cap)


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


class TestKnownPricesAndFloors(unittest.TestCase):
    """v0.18: preset paid models are priced by default; per-family token
    floors; prompt chars counted in the estimate."""

    def test_preset_paid_model_priced_without_explicit_prices(self):
        total, missing = worst_case_cost(
            models=["nvidia/nemotron-3-super-120b-a12b"],
            judge_models=["some/judge:free"],
            synth_model="some/judge:free",
            question="q?",
            max_tokens=500,
            prices={},
            free_set=set(),
        )
        self.assertIsNone(missing)
        self.assertGreater(total, 0.0)

    def test_explicit_prices_override_known(self):
        kw = dict(models=["nvidia/nemotron-3-super-120b-a12b"],
                  judge_models=[], synth_model="x:free",
                  question="q?", max_tokens=500, free_set=set())
        default_total, _ = worst_case_cost(prices={}, **kw)
        pricey_total, _ = worst_case_cost(
            prices={"nvidia/nemotron-3-super-120b-a12b":
                    {"input": 9.0, "output": 9.0}}, **kw)
        self.assertGreater(pricey_total, default_total)

    def test_load_prices_merges_known_and_spec_wins(self):
        prices = load_prices(
            '{"nvidia/nemotron-3-super-120b-a12b": '
            '{"input": 9.0, "output": 9.0}}')
        self.assertEqual(
            prices["nvidia/nemotron-3-super-120b-a12b"],
            {"input": 9.0, "output": 9.0})
        self.assertEqual(
            load_prices(None)["nvidia/nemotron-3-super-120b-a12b"],
            {"input": 0.30, "output": 2.40})

    def test_token_floors(self):
        self.assertEqual(effective_max_tokens("openai/gpt-5", 800), 8000)
        # mini is checked before gpt-5: 4000, not 8000.
        self.assertEqual(
            effective_max_tokens("openai/gpt-5-mini", 800), 4000)
        self.assertEqual(
            effective_max_tokens("anthropic/claude-sonnet-4", 800), 2500)
        self.assertEqual(
            effective_max_tokens("google/gemini-3-flash-preview", 800), 8000)
        self.assertEqual(effective_max_tokens("some/other-model", 800), 800)
        # A requested cap above the floor is kept.
        self.assertEqual(effective_max_tokens("openai/gpt-5", 9000), 9000)

    def test_synth_cap_floor(self):
        self.assertEqual(synth_cap("some/model", 800), 4000)
        self.assertEqual(synth_cap("openai/gpt-5", 800), 8000)
        self.assertEqual(synth_cap("some/model", 5000), 5000)

    def test_prompt_chars_counted_in_cost(self):
        kw = dict(models=["a/model"], judge_models=[],
                  synth_model="a/model", max_tokens=500,
                  prices={"a/model": {"input": 1.0, "output": 1.0}},
                  free_set=set())
        small, _ = worst_case_cost(question="x", prompt_chars=4, **kw)
        big, _ = worst_case_cost(question="x", prompt_chars=40000, **kw)
        self.assertGreater(big, small)

    def test_completion_cap_mirrors_cost_formula(self):
        # panel 3x500 + judge 2x900 + synth floor 4000
        self.assertEqual(
            completion_cap(["a/model"], ["j/model"], "s/model", 500),
            1500 + 1800 + 4000)
        # panel floor applies: 3x8000 for gpt-5
        self.assertEqual(
            completion_cap(["openai/gpt-5"], ["j/model"], "s/model", 500),
            24000 + 1800 + 4000)


if __name__ == "__main__":
    unittest.main()
