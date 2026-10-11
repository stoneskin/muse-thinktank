# muse-thinktank

Multi-model evaluation harness and results, powered by Muse (Meta).

Two things live here, and they are **not independent**: **(1)** an eval harness
that benchmarks LLMs on stock trading analysis and code/design, producing
the model profiles; **(2)** the design doc for a multi-model "think tank"
scheduler (fan-out → judge → synth) that **uses those profiles to pick
panel members**. The eval exists to answer "which models should sit on
the think tank for this kind of question?"

## Quickstart

```bash
# Runners need only Python 3.10+ stdlib. Set your key:
export OPENROUTER_API_KEY=sk-or-...

# Dry run with the sample question:
python docs/eval/run_stock.py --models <model-id> \
    --questions examples/sample_questions.json \
    --out-dir /tmp/eval-out

# See docs/eval/methodology.md for scoring rubrics.
```

Full question sets are private (anti-contamination); see below.

## What's here

- `docs/eval/methodology.md` — **Scoring rubrics**, anti-contamination policy,
  budget guardrails. Start here to understand or reproduce results.
- `docs/model-profiles.md` — Living capability profiles: stock score / code
  score / notes per model. From real API calls, never from model names.
- `docs/eval/` — Reports (`mainstream-models/`, `stock-v2/`, `stock-v3/`),
  method reviews, runner scripts, and `questions-manifest.json`
  (SHA-256 of private questions for future verification).
- `docs/design.md` — Think-tank scheduler design. The scheduler reads
  `docs/model-profiles.md` to assemble the right panel per question type
  (e.g. stock-heavy questions → top stock scorers).
- `examples/` — Question file JSON schema + a sample question.

## What's NOT here

Eval questions and raw model outputs are private (see `methodology.md`).
Planned open-source: 6 months after evaluated models' training cutoff,
verifiable against `questions-manifest.json`.

## Key findings (2026-10-11)

- **Stock**: 10/11 flagship models scored 15/15 on basic questions — v3 harder
  questions (options Greeks, portfolio optimization, robust Kelly, backtest scripts)
  finally separated them (19.5 vs 15.5).
- **Code**: DeepSeek v4 Pro 15/15; minimax-m3 ($0.30/1M) hit 19.5/20 on v3 stock —
  best value overall.
- **Methodology lesson**: Numerical questions don't differentiate LLMs;
  engineering judgment under constraints does.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Real API calls only — never score
from a model's name.

## License

Apache-2.0. See [LICENSE](LICENSE).
