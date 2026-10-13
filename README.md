# muse-thinktank

> **One prompt, a council of models, zero hallucinations.**

![muse-thinktank AI think tank](docs/thinktank-promo.webp)

[中文版](README_zh.md)

**Built for Muse users.** A multi-model deliberation orchestrator: one question goes to N models in parallel (panel), dual judges cross-validate, synth merges into a verdict. Pure Python standard library, zero dependencies.

**Model providers:** OpenRouter today; more carriers planned (see Roadmap).

```
Your question → [panel: N models in parallel] → [judge ×2 cross-validation] → [synth merge] → verdict
```

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-green.svg)]()
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

> **New here?** Start with the [User Guide](docs/USER-GUIDE.md) — from zero to your first run in 15 minutes.
> （中文用户：先看[用户使用说明](docs/USER-GUIDE_zh.md)。)

## Quickstart

```bash
export OPENROUTER_API_KEY=<redacted>   # get one free at https://openrouter.ai/keys
python3 thinktank.py ask \
  --models nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3-super-120b-a12b:free \
  --judge-model nvidia/nemotron-3-ultra-550b-a55b:free \
  "Analyze Tesla's risks over the next 3 months"
```

The verdict goes to stdout; progress goes to stderr. Run `--estimate` first to see the cost:

```bash
python3 thinktank.py ask --estimate --models <...> "your question"
# prints: call count, token cap, cost cap, ETA
```

## Architecture

```mermaid
flowchart LR
    Q[Question] --> E[--estimate cost check]
    E --> H[health-check]
    H --> P[panel: N models parallel]
    P --> J1[judge-A scores]
    P --> J2[judge-B scores]
    J1 --> C{agree?}
    J2 --> C
    C -->|yes| S[synth merge]
    C -->|no| HU[human review]
    S --> O[verdict]
```

One entry point: `thinktank.py` + `tt/` package (stdlib only: `urllib` + `json` + `argparse`).

**AI assistants**: see [AI_SETUP.md](AI_SETUP.md) for machine-readable install & operate instructions.

## Key Features

| Feature | Pain point | Effect |
|---|---|---|
| **Dual-judge cross-validation** | A single judge hallucinating unnoticed | Disagreement auto-escalates to human |
| **Real-time data injection** (`--context-data`) | Stale training data (e.g. 2024 knowledge answering 2026 stock questions) | Orchestrator pre-searches live data; models analyze real numbers |
| **Dynamic member selection** | Free models flaky | Auto-filter by historical success rate × latency |
| **Judge blacklist** (v0.7) | Unreliable judges keep failing | 2 consecutive failures → blacklisted (24h cooldown) |
| **Anti-fabrication validator** (v0.6) | Models inventing outputs | Validates claimed vs actual runs; flags fabrication |
| **Chunked PR review** (v0.8/v0.9) | Large diffs crash judges (19k-token inputs) | 4-step pipeline: skeleton → chunk → review → consistency check |
| **Fail-open / Fail-closed** | One dead model kills the round | Panel degrades gracefully; judges all-down → human |
| **Disagreement entropy** | No measure of panel divergence | Computed per round; scaffolds multi-round debate |

## Advanced

```bash
# Real-time data injection (must-have for time-sensitive questions)
python3 thinktank.py ask --context-data data.json \
  --models <...> "Analyze MSFT's current valuation"
# data.json: {"preamble": "...", "as_of": "...", "facts": {"price": "..."}}

# Dual judges (default: single)
python3 thinktank.py ask --judge-model <A> --judge-model2 <B> "..."

# Judge verdict only, skip synth (saves one call)
python3 thinktank.py ask --verdict "..."

# Show all answers side by side, human picks
python3 thinktank.py ask --show-all "..."

# Dynamic member selection (remembers model track record)
python3 thinktank.py ask --member-state ./members.json --capability-scores ./scores.json "..."

# Generate scores.json from the human-maintained model profiles:
python3 -m tt.profiles_to_scores docs/model-profiles.md > scores.json
# Blends stock 40% + code 40% + quant 20%, normalized to 0.0-1.0.
# Regenerate after every profiles.md update.

# Public benchmark priors (v0.5): LMArena + OpenRouter stability as base scores
python3 thinktank.py ask --priors --models <...> "..."
# Blends 70% LMArena capability + 30% stability (model age × rate limits).
# Your own --capability-scores override priors. 6h local cache, keyless.

# Backup models (v0.5): fill panel gaps automatically
python3 thinktank.py ask --models <A>,<B> --backup-models <C>,<D> --min-panel 2 "..."
# If panel drops below --min-panel (health check or mid-run failures),
# backups promote in order. Fail-closed only if still below minimum.

# Red-team mode (v0.5): critics attack the draft, adjudicator grades findings
python3 thinktank.py ask --red-team \
  --models <...> --judge-model <...> \
  --critic-models <...> \  # optional, defaults to panel models
  "Is this architecture sound?"
# Output: RED TEAM REPORT with verdict (revise/accept) and severity-graded
# findings (critical/major/minor; nitpicks filtered out)
```

# Chunked PR review (v0.9): 4-step pipeline for large diffs
python3 thinktank.py ask --pr-diff https://github.com/owner/repo/pull/123 \
  --chunk-tokens 3000 --models <...> "Review this PR"
# 1. Skeleton extraction (deterministic, no model call)
# 2. Split diff by file into ~3k-token chunks
# 3. Each chunk reviewed with global skeleton + local diff
# 4. Synth checks cross-file consistency
# Auto-triggers when diff > 2× chunk-tokens. --chunk-tokens 0 disables.

# Judge blacklist (v0.7): auto-avoid unreliable judges
# 2 consecutive judge failures → blacklisted for 24h (warning at startup)

# Anti-fabrication validator (v0.6)
python3 -m tt.validator --file output.md --model <id>
# Checks if model outputs match actual runs; flags invented results

See `examples/stock-analysis/` for the full "prepare-data-first" pattern.

## Examples

- **[Stock analysis](examples/stock-analysis/)** — inject real-time market data
  via `--context-data`; panel reasons over fresh numbers, not stale memory.
- **[Code review](examples/code-review/)** — point `--pr-diff` at a public
  GitHub PR; the diff is fetched automatically and a multi-model panel
  reviews the actual code. (This repo's own PR #1 was reviewed this way.)

## Philosophy

[The human–AI relationship](docs/human-ai-relationship.md) — why this tool
exists: AI amplifies human capability, but direction and taste are forever
human. ([中文版](docs/human-ai-relationship_zh.md))

## Contributing & Roadmap

- Issues / PRs welcome; look for the `good first issue` label
- PRs should include `--estimate` output (prove you didn't burn the budget)
- Roadmap: streaming output → Web UI → benchmark suite → multi-round debate convergence → **multi-carrier support** (beyond OpenRouter)

## Design Docs

[docs/design.md](docs/design.md) (work modes, judge powers, review framework) and
[docs/model-profiles.md](docs/model-profiles.md) (model capability profiles).

## Status

v0.9 (2026-10-13): chunked PR review — 4-step pipeline (skeleton → chunk → review → consistency check) for large diffs; "skeleton resident, details on demand."
v0.8 (2026-10-13): map-reduce diff chunking (`--chunk-tokens`).
v0.7 (2026-10-13): judge blacklist — 2 consecutive failures → 24h cooldown.
v0.6 (2026-10-13): anti-fabrication validator + judge repair-retry (tolerant JSON parsing).
v0.5 (2026-10-12): red-team mode (`--red-team`) — critics attack the draft, adjudicator grades findings by severity; public benchmark priors (`--priors`) — LMArena + OpenRouter stability as base capability scores.
v0.3b (2026-10-12): dual judges, dynamic member selection, real-time data injection (`--context-data`), think-tank review framework.

## License

Apache-2.0
