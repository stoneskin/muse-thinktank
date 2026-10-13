# Changelog

All notable changes to muse-thinktank are recorded here, matching the
[GitHub Releases](https://github.com/stoneskin/muse-thinktank/releases).
Design rationale lives in [docs/design.md](docs/design.md).

## [Unreleased]

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
