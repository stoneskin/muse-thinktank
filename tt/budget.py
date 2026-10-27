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
    {"model-id": {"input": 0.27, "output": 1.10}} ($ per 1M tokens).

    v0.18: starts from KNOWN_PRICES so a paid model the harness itself
    ships in a tier preset (e.g. the paid super-120b kept after its :free
    variant was delisted 2026-10-27) never fail-closes for a missing
    price table. An explicit --prices entry always wins.
    """
    prices = dict(KNOWN_PRICES)
    if not spec:
        return prices
    text = spec
    if os.path.exists(spec):
        text = open(spec).read()
    try:
        data = json.loads(text)
    except ValueError:
        raise SystemExit("error: --prices parse failed (not valid JSON)")
    if not isinstance(data, dict):
        raise SystemExit("error: --prices must be {model: {input, output}}")
    prices.update(data)
    return prices


# v0.18: durable default prices for paid models the harness itself ships
# in a tier preset. Source: OpenRouter catalog, 2026-10-27. Update here
# when a preset model changes; --prices always overrides.
KNOWN_PRICES = {
    "nvidia/nemotron-3-super-120b-a12b": {"input": 0.30, "output": 2.40},
}


# v0.18: per-family completion-token floors. Reasoning models burn the
# cap on hidden reasoning before producing body text, so one global
# default starves them (2026-10-23: panel default 800 -> empty replies;
# --max-tokens 8000 revived the same panel 3/3). Floors only raise the
# cap, never lower it: max_tokens is a ceiling, not usage (2026-10-11
# rule). First substring match wins -- check gpt-5-mini before gpt-5.
TOKEN_FLOORS = [
    ("gpt-5-mini", 4000),
    ("gpt-5", 8000),
    ("claude", 2500),
    ("gemini", 8000),
]


def effective_max_tokens(model, requested):
    """Completion cap actually used for one call: the requested cap
    raised to the model family's floor when one applies."""
    for substr, floor in TOKEN_FLOORS:
        if substr in (model or ""):
            return max(int(requested), floor)
    return int(requested)


# v0.18: synth must reproduce every panel answer plus the judge verdict,
# so its cap gets its own floor above the panel cap. (2026-10-27: a 2500
# synth cap truncated the verdict mid-section-5.)
SYNTH_MIN_TOKENS = 4000


def synth_cap(model, requested):
    """Completion cap for the synth call."""
    return max(SYNTH_MIN_TOKENS, effective_max_tokens(model, requested))


def worst_case_cost(models, judge_models, synth_model, question, max_tokens,
                   prices, free_set, prompt_chars=None):
    """Worst-path cost in USD, or (None, missing_model) when a paid model
    has no price entry. Free-verified models cost $0 by construction.

    v0.18: per-model effective caps (floors) so the estimate uses the
    same ceilings the run does; panel worst case counts one retry at
    double tokens (panel retry, v0.18), matching the judge x2 already
    counted for repair-retry. prompt_chars is the full prompt length
    (question + injected context); without it the estimate silently
    ignores context tokens (2026-10-23: ~2.7x underestimate).
    KNOWN_PRICES is the base table here too, so a caller passing a bare
    {} can never reintroduce the missing-price fail-closed; an explicit
    entry always wins.
    """
    merged = dict(KNOWN_PRICES)
    merged.update(prices)
    prices = merged
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
    if prompt_chars is None:
        prompt_chars = len(question)
    q_tok = prompt_chars / 4.0
    total = 0.0
    for m in models:
        pi, po = per1m[m]
        cap = effective_max_tokens(m, max_tokens)
        # first attempt + one retry at double tokens
        total += q_tok / 1e6 * pi + 3 * cap / 1e6 * po
    # judge prompt carries all answers at worst-case length
    # (each answer up to its effective cap, retry doubling included)
    # v0.6: x2 for repair-retry (one retry max per judge)
    judge_prompt = (sum(2 * effective_max_tokens(m, max_tokens)
                        for m in models) + prompt_chars) / 4.0
    for jm in judge_models:
        pj_i, pj_o = per1m[jm]
        judge_max = max(900, effective_max_tokens(jm, max_tokens))
        total += 2 * (judge_prompt / 1e6 * pj_i + judge_max / 1e6 * pj_o)
    ps_i, ps_o = per1m[synth_model]
    total += judge_prompt / 1e6 * ps_i + synth_cap(synth_model, max_tokens) / 1e6 * ps_o
    return total, None


def completion_cap(models, judge_models, synth_model, max_tokens,
                   n_critics=0):
    """Worst-case completion-token cap for the estimate printout, using
    the same ceilings as worst_case_cost: panel first attempt + one
    double-token retry, judges with repair-retry x2, synth floor, plus
    red-team critics/adjudicator when present."""
    total = 0
    for m in models:
        total += 3 * effective_max_tokens(m, max_tokens)
    for jm in judge_models:
        total += 2 * max(900, effective_max_tokens(jm, max_tokens))
    total += synth_cap(synth_model, max_tokens)
    if n_critics:
        total += n_critics * max_tokens + synth_cap(synth_model, max_tokens)
    return total
