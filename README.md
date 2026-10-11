# muse-thinktank

Multi-model evaluation harness and results, powered by Muse (Meta).

This repo contains the **methodology, results, and model profiles** from systematic
evaluations of LLMs on two dimensions: **stock trading analysis** and **code/design**.

## What's here

- `docs/model-profiles.md` — Living capability profiles for each tested model:
  stock score / code score / notes. Updated from real API calls, never from model names.
- `docs/eval/` — Evaluation reports:
  - `mainstream-models/2026-10-11.md` — 11 US/China flagship models × 6 questions
  - `stock-v2-2026-10-11.md` / `stock-v3-2026-10-11.md` — Harder stock question iterations
  - `method-review-*.md` — Multi-model panel reviews of the eval methodology itself
- `docs/eval/run_stock.py`, `run_code.py` — Eval runners with budget guardrails
  (per-model cost cap, fail-fast on repeated failures, honest ledger).
- `docs/design.md` — Design doc for the think-tank scheduler (multi-model fan-out
  → judge → synth).

## What's NOT here

Eval questions and raw model outputs are kept in a private repo to avoid
contamination (models training on the test set). The runners expect a questions
JSON file; see the scripts for the format.

## Key findings (2026-10-11)

- **Stock**: 10/11 flagship models scored 15/15 on basic questions — v3 harder
  questions (options Greeks, portfolio optimization, robust Kelly, backtest scripts)
  finally separated them (19.5 vs 15.5).
- **Code**: DeepSeek v4 Pro 15/15; minimax-m3 ($0.30/1M) hit 19.5/20 on v3 stock —
  best value overall.
- **Methodology lesson**: Numerical questions don't differentiate LLMs;
  engineering judgment under constraints does.

## License

Apache-2.0. See [LICENSE](LICENSE).
