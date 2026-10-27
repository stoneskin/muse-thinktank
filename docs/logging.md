# thinktank run logs (v0.17)

One structured JSON log per real run. This is the diagnostic record:
when a run fails, the log file says **where it died and what happened**
per model -- not just "empty response".

## Location and naming

- Default directory: `~/workspace/thinktank-logs/` (outside the repo --
  logs are never committed). Override with `--log-dir DIR`.
- One file per run:
  `thinktank-<UTC YYYYMMDDTHHMMSSZ>-<8 hex run id>.json`
  e.g. `thinktank-20261027T040512Z-9f3a1c2e.json`.
- The wrapper (`scripts/tt-go.py`) needs no change: it passes
  `--log-dir` through like any other flag, and its step-1 estimate run
  produces **no** log (the estimate branch returns before the logger is
  created). `--replay` / `--golden` / `--golden-run` also produce no log.

## Tracing a run by id

The run id is the 8 hex chars at the end of the filename, and also the
`run_id` field inside the file. To find a run: list the directory by
time, or grep for the id:

```sh
ls -t ~/workspace/thinktank-logs/ | head
grep -l '"run_id": "9f3a1c2e"' ~/workspace/thinktank-logs/*.json
```

## Field glossary

| Field | Meaning |
|---|---|
| `run_id`, `started_utc`, `finished_utc` | Run identity and UTC timestamps (ISO 8601). |
| `status` | `completed` (a verdict/show-all/red-team path finished and wrote the log explicitly) or `aborted` (the run died mid-flight: a fail-closed `SystemExit` triggered the atexit flush). |
| `last_phase` | Furthest phase reached: `startup`, `cost-check`, `member-selection`, `health-check`, `context`, `panel`, `judge`, `show-all`, `verdict`, `synth`, `red-team-critics`, `red-team-adjudicator`. An `aborted` log's `last_phase` is where to look first. |
| `params` | Resolved run parameters: tier, models requested/final, judge(s), synth, max_tokens, temperature, panel_timeout, budget, min_panel, red_team, practitioner, context-data path, record path, **question length only** (never the question text). `models_final` is the panel after health check; phase-1b backup promotions appear under `backups`, not in `models_final`. |
| `estimate` | Worst-path cost estimate vs budget, and the missing-price model if the estimate was impossible (`worst_cost: null`). |
| `context` | Context-data path, facts count, facts character count, and the load error if any (e.g. "context file unreadable" when a Markdown file was passed as JSON). Fact *values* are never stored. |
| `member_selection` | Requested vs kept vs dropped models from dynamic member selection (empty dropped list when selection is off). |
| `health_checks` | One entry per health-check phase (`pre-panel`, `backup-promotion`, `phase1b-backup`), each with per-model: ok, error (raw provider error, e.g. `HTTP 404: ...` from a router -- not collapsed to "empty"), `finish_reason`, elapsed, cost. |
| `panel` | Per panel model: ok/fail, error summary (capped at 300 chars), `finish_reason`, `truncated`, prompt/completion/reasoning/total tokens, cost, elapsed, answer text length. **Panel answer texts are not stored** (lengths only). The key diagnosis from 2026-10-26: `finish_reason: "length"` + `total_tokens` at the cap + visible text length 0 = hidden reasoning ate the token budget; `error: "HTTP ..."` = provider-side failure; empty text with no error and no `length` = a genuinely empty reply. |
| `backups` | Every backup attempt (health-check-promoted or phase-1b): model, promoted or not, error, `finish_reason`, tokens, cost, elapsed, text length. |
| `judge` | Per judge model: winner, confidence, `repaired` (recovered on the repair retry), `attempts` (1 or 2), `repair_mode` (`first-ok`, `repair` = contract failure with reason fed back, `retry` = empty/error reply with a plain retry), error, `finish_reason`, cost; plus section-level `dual_ok`, `dual_reason`, `entropy`. |
| `synth` | Synth model, ok, error, `finish_reason`, cost, text length. |
| `redteam` | Critics (model, ok, repaired, findings count, cost) and adjudicator (ok, repaired, verdict, confidence, cost). |
| `verdict`, `verdict_source` | The full verdict text (this is the run's output, so it is stored in full) and where it came from: `synth`, `verdict-branch`, `verdict-branch-fallback-side-by-side`, `show-all-human-pending` (verdict null -- a human still has to pick), `red-team-report-stdout` (verdict null -- the report went to stdout), or null for aborted runs. |
| `spent` | Total USD actually spent by the run (all phases the main flow accounts for). |

## Retention: 90 days

At each real run start, the tool best-effort deletes its own log files
older than 90 days (by file mtime) in the log directory
(`tt/runlog.py: prune_logs`). Only files matching the
`thinktank-<timestamp>-<run id>.json` filename pattern are candidates;
any other file in the directory is never touched, however old.

## Failure behavior

Logging never fails a run. If the log directory cannot be created or
the file cannot be written, exactly one stderr warning is printed
(`[thinktank] WARNING: run log write failed ...`) and the run
continues. A run that dies via a fail-closed exit still gets a log
(status `aborted`) through an atexit flush -- except runs that exit
before argument parsing finishes (bad flags, `--estimate`, `--replay`,
`--golden`), which never start a logger.

## Run log vs `--record`

They are different artifacts for different jobs:

- `--record PATH` is a **versioned audit artifact for replay**
  (schema + hash, `tt/run_record.py`): inputs, models, per-stage
  outputs, cost, verdict. It is written **only for runs that reach a
  verdict** (synth, show-all, verdict, red-team paths). Fail-closed runs
  (panel below minimum, judge rejected everything, budget exceeded)
  have no verdict by design, so they produce no `--record` file.
- The run log is a **diagnostic record**: it is written for every real
  run **including failed ones**, precisely so a fail-closed run can be
  diagnosed afterwards.

History note (2026-10-26): `--record` through the wrapper produced no
file in four-plus runs because the `--verdict` branch printed the
winner and returned without ever calling `set_verdict`/`save`, and the
red-team path never received the record object at all. Both are fixed
in v0.17: the verdict branch now sets the verdict and saves, and the
red-team path saves a marker record (`[red-team report printed to
stdout]`). The wrapper (`tt-go.py`) was never the problem -- it passes
all arguments through unchanged.
