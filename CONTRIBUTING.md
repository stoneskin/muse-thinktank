# Contributing

## What this repo is

The **public** half of the muse-thinktank eval project: methodology, reports,
model profiles, and runner scripts. Eval questions and raw model outputs live
in a private repo (anti-contamination — see `docs/eval/methodology.md`).

## What you can contribute

- **New model results**: Run the eval on a model we haven't tested, using the
  same questions version and methodology. Open a PR with the report.
- **Methodology improvements**: Better rubrics, harder questions, new dimensions.
- **Runner fixes**: Budget guardrails, sandboxing, output parsing.

## How to add a model evaluation

1. Get the questions file (ask the maintainer for the private repo access,
   or use `examples/sample_questions.json` to test the pipeline).
2. Set `OPENROUTER_API_KEY` in your environment.
3. Run: `python docs/eval/run_stock.py --models <model-id> --questions <file>`
4. Score using `docs/eval/methodology.md` rubrics.
5. Add results to `docs/model-profiles.md` and open a PR.

## Rules

- **Real API calls only.** Never score a model from its name, marketing, or vibes.
- **Disclose costs.** Include per-model spend in your report.
- **Don't publish private questions.** If you have private repo access,
  never copy question prompts into the public repo, issues, or PRs.
