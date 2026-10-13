"""v0.4 module: tt/budget.py."""

import json
import os
import threading
from .util import log

class BudgetExceeded(Exception):
    """v0.4: raised when runtime spending exceeds the hard limit."""
    pass


class RuntimeBudget:
    """v0.4: thread-safe runtime cost circuit breaker.

    Charge after every API call with the actual measured cost.
    Raises BudgetExceeded when spending passes budget * hard_limit_ratio.
    The 10% headroom absorbs token-count variance vs the static estimate.
    """
    def __init__(self, budget_usd, hard_limit_ratio=1.1):
        import threading
        self.limit = budget_usd * hard_limit_ratio
        self.budget = budget_usd
        self.spent = 0.0
        self._lock = threading.Lock()

    def charge(self, cost_usd):
        with self._lock:
            self.spent += cost_usd
            if self.spent > self.limit:
                raise BudgetExceeded(
                    "spent $%.4f > hard limit $%.4f (budget $%.2f)" %
                    (self.spent, self.limit, self.budget))
            return self.spent


def load_prices(spec):
    """--prices: JSON string or path to JSON file:
    {"model-id": {"input": 0.27, "output": 1.10}} ($ per 1M tokens)."""
    if not spec:
        return {}
    text = spec
    if os.path.exists(spec):
        text = open(spec).read()
    try:
        data = json.loads(text)
    except ValueError:
        raise SystemExit("error: --prices parse failed (not valid JSON)")
    if not isinstance(data, dict):
        raise SystemExit("error: --prices must be {model: {input, output}}")
    return data


def worst_case_cost(models, judge_models, synth_model, question, max_tokens,
                   prices, free_set):
    """Worst-path cost in USD, or (None, missing_model) when a paid model
    has no price entry. Free-verified models cost $0 by construction."""
    unknown = []
    per1m = {}
    for m in set(models + judge_models + [synth_model]):
        base = m[:-5] if m.endswith(":free") else m
        if m.endswith(":free") or base in free_set or m in free_set:
            # :free suffix = explicitly free endpoint; free_set covers free ids without suffix
            per1m[m] = (0.0, 0.0)
        elif m in prices:
            p = prices[m]
            try:
                per1m[m] = (float(p["input"]), float(p["output"]))
            except (KeyError, ValueError, TypeError):
                unknown.append(m)
        else:
            unknown.append(m)
    if unknown:
        return None, unknown[0]
    # worst case: every call maxes out completions; prompts ~ chars/4
    judge_max = max(900, max_tokens)
    synth_max = max(1200, max_tokens)
    q_tok = len(question) / 4.0
    total = 0.0
    for m in models:
        pi, po = per1m[m]
        total += q_tok / 1e6 * pi + max_tokens / 1e6 * po
    # judge prompt carries all answers at worst-case length
    # v0.6: x2 for repair-retry (one retry max per judge)
    judge_prompt = (len(models) * max_tokens * 2 + len(question)) / 4.0
    for jm in judge_models:
        pj_i, pj_o = per1m[jm]
        total += 2 * (judge_prompt / 1e6 * pj_i + judge_max / 1e6 * pj_o)
    ps_i, ps_o = per1m[synth_model]
    total += judge_prompt / 1e6 * ps_i + synth_max / 1e6 * ps_o
    return total, None
