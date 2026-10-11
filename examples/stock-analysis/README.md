# Stock Analysis Example

Demonstrates the **prepare-data-first** pattern for time-sensitive domains.

Panel models have stale training data. For stock analysis, Muse (the orchestrator)
pre-searches real-time data per `input-checklist.md`, then injects it via
`thinktank.py --context-data context-data.sample.json`.

Flow:
1. Muse searches real-time data (price, earnings, technicals) per checklist
2. Muse builds `context-data.json` with `{"preamble", "as_of", "facts"}`
3. `thinktank.py ask --context-data context-data.json "..."`
4. Panel models analyze using injected numbers, not training memory

See `context-data.sample.json` for the format (values are illustrative).
