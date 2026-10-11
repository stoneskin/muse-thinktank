# Evaluation Methodology

How models are tested, scored, and compared. This document defines the rubrics
so anyone can reproduce or audit the results.

## Dimensions

Two independent dimensions, scored separately:

| Dimension | What it tests | Max |
|---|---|---|
| **Stock** | Stock trading analysis: concepts, indicators, strategy judgment | 15 (v1) / 20 (v2/v3) |
| **Code** | Programming and design: algorithms, data structures, system design | 15 |

## Stock v1 (6 questions, 15 points)

| ID | Topic | Points | Rubric |
|---|---|---|---|
| S1 | RSI interpretation | 2.5 | Correct RSI reading 1; overbought/oversold judgment 1; actionable advice 0.5 |
| S2 | Moving average crossover | 2.5 | Correct signal identification 1; false-signal caveat 1; position sizing mention 0.5 |
| S3 | VIX / fear gauge | 2.5 | Correct VIX interpretation 1; regime context 1; hedge suggestion 0.5 |
| S4 | Multi-indicator synthesis | 2.5 | No contradiction 1; weighted conclusion 1; risk acknowledgment 0.5 |
| S5 | Strategy design | 2.5 | Entry/exit rules 1; risk management 1; realistic assumptions 0.5 |
| S6 | Trap question (insufficient info) | 2.5 | Recognizing "wait" is correct 1.5; explaining why 1 |

**Key rule**: S6 rewards *not acting* when information is insufficient.
A confident wrong answer scores 0.

## Stock v2/v3 (4 questions, 20 points, 5 each)

Harder, engineering-focused. Each question has code + explanation parts.

| ID | Topic | Code (3) | Explanation (2) |
|---|---|---|---|
| S4 | Options IV surface interpolation | Runs 1; correct method 1; correct numbers 1 | Keywords 2 (any 2 of 4) |
| S5 | Portfolio optimization | Runs 1; correct optimizer 1; correct numbers 1 | Keywords 2 (any 2 of 3) |
| S6 | Robust Kelly criterion | Correct estimation 1.5; Kelly calc 1 | Fat-tail analysis 1; robust fix 1.5 |
| S7 | Backtest script | Runs 2 | 5 metrics 1; costs 1; no-lookahead 1 |

**Anti-hardcoding**: Code must read from data files. Hardcoded constants = 0 for code part.
Checked by: (1) keyword scan for embedded data, (2) running against perturbed data.

## Code (3 problems, 15 points, 5 each)

| ID | Topic | Correctness (3) | Design (2) |
|---|---|---|---|
| P1 | Algorithm + hidden tests | Passes visible 1; passes hidden 2 | — |
| P2 | Data structure design | Correct API 1; edge cases 1 | Complexity analysis 1 |
| P3 | System design | Workable architecture 1.5 | Trade-off discussion 1.5 |

P1 hidden tests are generated per-run (not in the prompt) to prevent memorization.

## Scoring process

1. **Model calls**: Via OpenRouter API, fixed temperature 0.7, documented token limits.
2. **Code questions**: Extract Python blocks, run in sandbox with data files mounted.
   Timeout 15s. Non-zero exit = 0 for code part (but explanation part still scored).
3. **Explanation questions**: Keyword matching (listed per question) + human spot-check.
4. **Reliability**: Empty/timeout responses are retried once, then scored 0.
   Reliability is tracked separately from capability (see model profiles).

## Anti-contamination

- Question prompts and raw model outputs live in a **private repo**.
- This public repo publishes a **SHA-256 manifest** (`questions-manifest.json`)
  so future question releases can be verified untampered.
- Questions are rotated each major version (v1 → v2 → v3).
- Planned release: questions stay private by default; open-sourced only if there
  is concrete demand or a specific need. The manifest lets anyone verify
  untampered questions if/when that happens.

## Budget guardrails

- Per-model cap: $0.50 per eval round (ask before exceeding).
- Fail-fast: 2 consecutive failures → stop, score 0, no token top-up.
- Honest ledger: API usage costs recorded per call, even for failures.
- Free models preferred; paid only with explicit approval and cost estimate.
