# Changelog

All notable changes to muse-thinktank are recorded here, matching the
[GitHub Releases](https://github.com/stoneskin/muse-thinktank/releases).
Design rationale lives in [docs/design.md](docs/design.md).

## [Unreleased]

## [v0.16.0] - 2026-10-21

- **Harness stability** (incident: 2026-10-21 red-team run shipped with 1/3 critics usable and a truncated winning draft, neither declared in the report):
  - `chat_json_repair`: judge / critic / adjudicator outputs that fail their JSON contract get exactly one repair retry with the failure reason fed back; empty or errored first replies get one plain retry. The second call runs at double the token cap (reasoning models starved by the cap were returning empty). Two failures and the role is out — same circuit-breaker rule as panel members.
  - Critic substitution: failed red-team critics are replaced from the backup pool before the phase accepts a degraded panel. When `--backup-models` is omitted, the pool is auto-derived from `--capability-scores` (top-scored models outside panel/judge).
  - Truncation gate: if the judge's winning answer was truncated, confidence is capped at medium and the fact is stated in the report.
  - Completeness header: every run prints a `completeness:` line (panel x/y · judge state · winner intact/truncated; red-team reports add critics x/y, repairs, substitutes, adjudicator state). Degradation is declared in the deliverable, not just in stderr logs.
  - `scripts/test_stability.py`: offline fault-injection regression tests pinning these five failure shapes (contract failure, substitution, fail-closed, truncation gate, empty-first-reply).

## [v0.9.0] - 2026-10-13

- **Chunked PR review** (§15): 4-step pipeline for large diffs — skeleton extraction → chunk → review → consistency check. "Skeleton resident, details on demand" (mimics human reviewers). Auto-triggers when diff > 2× `--chunk-tokens`.
- `tt/skeleton.py`: deterministic extraction of function/class/import changes (no model call).
- `tt/chunker.py`: split diff by file into ~3k-token chunks.

## [v0.8.0] - 2026-10-13

- Map-reduce diff chunking (`--chunk-tokens`, default 3000). Large diffs that used to crash judges (19k-token inputs) now complete.

## [v0.7.1] - 2026-10-13

- Judge blacklist cooldown: 24h auto-unban.
- Backup health-check max 3 rounds (avoid burning budget on long backup lists).

## [v0.7.0] - 2026-10-13

- **Judge blacklist**: 2 consecutive judge failures → blacklisted (startup warning).

## [v0.6.0] - 2026-10-13

- **Anti-fabrication validator** (`tt/validator.py`): checks model-claimed outputs vs actual runs.
- Judge repair-retry: tolerant JSON parsing (case-insensitive enums, string→int, default confidence) + 1 retry on format violation.

## [v0.5.0] - 2026-10-12

- Red-team mode (`--red-team`): critics attack draft, adjudicator grades by severity.
- Public benchmark priors (`--priors`): LMArena + OpenRouter stability as base scores.
- Backup models (`--backup-models`): auto-fill panel gaps.

## [v0.4.0] - 2026-10-12

- `--pr-diff`: fetch GitHub PR diff for code review.
- Judge anonymization + judge/panel overlap fail-closed.
- `--budget-headroom`: runtime budget abort at budget × headroom.
