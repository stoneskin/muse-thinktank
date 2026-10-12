# Code Review Example

Demonstrates using muse-thinktank as a **multi-model code review panel**.
Instead of pasting code manually, point `--pr-diff` at a public GitHub PR —
the diff is fetched automatically and injected into the panel prompt.

## Quick start

```bash
python thinktank.py ask \
  --models deepseek/deepseek-chat,anthropic/claude-sonnet-4.5 \
  --judge-model google/gemini-2.5-pro \
  --pr-diff https://github.com/<owner>/<repo>/pull/<n> \
  --budget 0.50 \
  "Review this PR diff for bugs, security issues, and design problems. \
   Verdict: APPROVE / REQUEST_CHANGES / BLOCKED."
```

What happens:
1. `fetch_pr_diff()` pulls the public `.diff` (no auth needed, 12KB cap)
2. The diff is injected into the panel prompt between
   `=== PR DIFF ===` markers
3. Each panel model reviews the **actual code**, not a summary
4. Judge cross-checks the reviews; disagreement escalates to human

## Why this matters

Earlier versions of this workflow pasted a *text summary* of the changes
("fixed injection, fixed deadlock"). Reviewers hallucinated — one claimed
the delimiter used "a PRNG seeded with system time" when the code actually
used `secrets.token_urlsafe`; another demanded `asyncio.gather` cleanup in
a codebase with no asyncio. Feeding the real diff eliminated that class
of error.

## Notes

- Works with public PRs only (no auth). Private repos: paste the diff
  into `--context-data` instead, or extend `fetch_pr_diff()` with a token.
- Judge must differ from panel models (fail-closed by default;
  `--allow-judge-overlap` overrides).
- Keep the review question specific: "find bugs" beats "review this".
