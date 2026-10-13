# Question Templates

> Why this exists: in real use, the biggest quality lever is not clever prompt
> wording — it is giving the panel a complete brief. A mediocre prompt with a
> full brief beats a "magic prompt" with a thin one. Steal the principle, not
> the spell.

## The four-part brief

Every question sent to the panel should carry these four parts:

1. **Decision** — what is being decided (go / no-go / revise)?
2. **Current state** — the facts on the ground right now.
3. **Constraints** — hard limits: stop levels, budgets, standing rules,
   deadlines that cannot be bent.
4. **Timeline** — when the decision must be made, and which upcoming events
   bound it.

Fill all four and even a plain prompt gets a good answer. Skip them and even
the best models start inventing.

## Universal assembly instructions

Appended to every run automatically — the operator never has to remember them:

1. The panel restates the question in its own words and confirms understanding
   **before** answering.
2. Every conclusion is labeled **[verified data]** or **[inference]**.
3. If the two judges disagree, present the disagreement honestly —
   never fabricate consensus.

## The templates

Each template = the four-part checklist + auto-fill sources + output
structure + an assembled example. Placeholders in `[BRACKETS]` are filled by
the operator from real data before the run.

### A. Pre-commit red team (deep tier)

Use before any hard-to-reverse action: opening exposure, signing, shipping.

- **Output structure:**
  1. Restate the plan to confirm understanding.
  2. The three most likely ways this loses money / goes wrong.
  3. Logical holes in the plan itself.
  4. If you were on the other side, how would you attack it?
  5. Verdict: go / revise / don't — with the single weakest link named.
- **Assembled example:** "Considering adding [SIZE] of [TICKER] at
  [ENTRY-ZONE] (current exposure [X]; stop [STOP]; catalyst: [EVENT] on
  [DATE]). Red team: find the three most likely ways this addition loses
  money."

### B. Time-sensitive signal deep-dive (deep tier)

Use when a trigger fires and a decision is due.

- **Auto-fill:** today's data snapshot, the plan file that defined the
  trigger, fresh news.
- **Output structure (six sections):** background → freshness →
  fundamentals (short/long) → technicals (short/long) → handling →
  risks.

### C. Periodic review (quick tier)

Use on a fixed cadence to calibrate the system, not the single decision.

- **Auto-fill:** the period's signal log, hit rate, execution deviations.
- **Output structure:**
  1. Top 3 holes in the current rules.
  2. Which standing rules were bent or violated (with instances).
  3. Concrete rule changes, specified down to exact trigger numbers.
  4. What to watch next period.

### D. Design review (quick or deep, by stakes)

Use at key decision points in a project.

- **Auto-fill:** relevant design docs, repo state.
- **Output structure:**
  1. Restate the design intent.
  2. Attack: the three likeliest failure points.
  3. Is there a simpler approach that achieves the same?
  4. Verdict: pass / revise.

### E. Offer / career decision (deep tier)

Use for job offers and negotiations.

- **Auto-fill:** the offer email verbatim, current compensation, market data.
- **Output structure:**
  1. Break down the offer: true value of base / bonus / equity.
  2. Market benchmark.
  3. Negotiation anchors and talking points.
  4. Risks (title regression, commute, scope).
  5. Verdict.

### F. Operator self-audit (deep tier)

Use periodically to find the operator's own systematic biases
(e.g. telling the user what they want to hear).

- **Auto-fill:** sampled reports and recommendations from the period,
  think-tank usage log.
- **Output structure:**
  1. Top 3 systematic biases, each with instances.
  2. What should have been flagged but wasn't; what was noise.
  3. Improvement list for next period.

## Three cold truths

1. The think tank is an amplifier, not an oracle. When a score looks wrong,
   suspect the harness (token limits, prompt format, parsing) before the
   model.
2. The bottleneck is usually question quality + context completeness, not
   model count. `--context-data` injection beats adding models.
3. Spend budget on high-stakes and pre-commit reviews, not curiosity.
