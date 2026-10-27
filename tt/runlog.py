"""v0.17 module: tt/runlog.py -- one structured JSON log per thinktank run.

Why this exists (2026-10-26): a heavy-reasoning panel failed with only
"empty response" in the stderr log -- no finish_reason, no token counts,
no way to tell a reasoning-cap starvation (finish_reason=length, visible
text 0) from a provider outage (HTTP 404/429) from a plain empty reply.
The run log closes that gap: every phase records per-model ok/fail,
finish_reason, truncation, token counts, cost, elapsed, and a capped
error summary, so a failed run can be diagnosed from the file alone.

One run = one file. Default directory is ~/workspace/thinktank-logs/
(outside the repo -- logs are never committed); --log-dir overrides it.
Filename: thinktank-<UTC YYYYMMDDTHHMMSSZ>-<8 hex run id>.json.

What is NOT in the log, deliberately:
- the question text (only its length) and panel answer texts (only
  lengths) -- the log is a diagnostic record, not a transcript;
- API keys / Authorization headers -- nothing in this module ever sees
  them, and thinktank.py must not put them into params;
- context fact VALUES -- only the context file path, facts count, and
  facts character count (see set_context).

Failure behavior: logging is best-effort. write() never raises; on
failure it prints exactly one stderr warning and the run continues.
prune_logs() likewise never raises and only ever deletes files matching
this tool's own filename pattern.

Retention: prune_logs() deletes own-pattern files older than 90 days
(by mtime) at each real run start. Files that do not match the pattern
are never touched, even if old.
"""

import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone

RETENTION_DAYS = 90

FILENAME_RE = re.compile(r"^thinktank-\d{8}T\d{6}Z-[0-9a-f]{8}\.json$")

_ERROR_CAP = 300


def default_log_dir():
    return os.path.expanduser("~/workspace/thinktank-logs")


def _summarize(text, cap=_ERROR_CAP):
    """Cap an error string for the log; None/empty stays None."""
    if not text:
        return None
    text = str(text)
    return text if len(text) <= cap else text[:cap] + "...[truncated]"


def _utc_now():
    return datetime.now(timezone.utc)


def prune_logs(log_dir, days=RETENTION_DAYS):
    """Delete this tool's own log files older than `days` (mtime).

    Only files matching FILENAME_RE are candidates; anything else in
    the directory is left alone. Best-effort: returns the number of
    files deleted, never raises.
    """
    try:
        if not log_dir or not os.path.isdir(log_dir):
            return 0
        cutoff = time.time() - days * 86400
        deleted = 0
        for name in os.listdir(log_dir):
            if not FILENAME_RE.match(name):
                continue
            path = os.path.join(log_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    deleted += 1
            except OSError:
                continue
        return deleted
    except OSError:
        return 0


class RunLog:
    """Accumulates one run's diagnostic record and writes it as JSON."""

    def __init__(self, log_dir, params):
        self.log_dir = (os.path.expanduser(log_dir) if log_dir
                        else default_log_dir())
        self.run_id = secrets.token_hex(4)
        now = _utc_now()
        self.started = now.isoformat()
        self.filename = ("thinktank-%s-%s.json"
                         % (now.strftime("%Y%m%dT%H%M%SZ"), self.run_id))
        self.path = os.path.join(self.log_dir, self.filename)
        self.written = False
        self.data = {
            "run_id": self.run_id,
            "started_utc": self.started,
            "finished_utc": None,
            "status": "running",
            "last_phase": "startup",
            "params": dict(params),
            "estimate": None,
            "context": None,
            "member_selection": None,
            "health_checks": [],
            "panel": [],
            "backups": [],
            "judge": None,
            "synth": None,
            "redteam": None,
            "verdict": None,
            "verdict_source": None,
            "spent": 0.0,
        }

    # -- phase setters (all plain data, no I/O) --

    def note_phase(self, phase):
        self.data["last_phase"] = phase

    def mark(self, status, phase=None):
        self.data["status"] = status
        if phase is not None:
            self.data["last_phase"] = phase

    def set_estimate(self, worst, missing, budget):
        self.data["estimate"] = {"worst_cost": worst,
                                 "missing_price_model": missing,
                                 "budget": budget}

    def set_context(self, path, facts_count, facts_chars, error=None):
        self.data["context"] = {"path": path,
                                "facts_count": facts_count,
                                "facts_chars": facts_chars,
                                "error": _summarize(error)}

    def set_member_selection(self, requested, kept, dropped):
        self.data["member_selection"] = {"requested": list(requested),
                                         "kept": list(kept),
                                         "dropped": list(dropped)}

    def add_health_check(self, phase, details):
        """details: list of {model, ok, error, finish_reason, elapsed, cost,
        attempts}. attempts (v0.18) shows whether the retry saved the
        model, so a retried-then-ok model is distinguishable from a
        first-try-ok one in post-mortems."""
        self.data["health_checks"].append({
            "phase": phase,
            "models": [{
                "model": d.get("model"),
                "ok": bool(d.get("ok")),
                "error": _summarize(d.get("error")),
                "finish_reason": d.get("finish_reason") or None,
                "elapsed": d.get("elapsed"),
                "cost": d.get("cost"),
                "attempts": d.get("attempts", 1),
            } for d in details],
        })

    def add_panel(self, entries):
        """entries: panel answer dicts (model, ok, error, finish_reason,
        truncated, usage, elapsed, cost, text length)."""
        for e in entries:
            usage = e.get("usage") or {}
            self.data["panel"].append({
                "model": e.get("model"),
                "ok": bool(e.get("ok")),
                "error": _summarize(e.get("error")),
                "finish_reason": e.get("finish_reason") or None,
                "truncated": bool(e.get("truncated")),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": usage.get("reasoning_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost": e.get("cost"),
                "elapsed": e.get("elapsed"),
                "text_length": len(e.get("text") or ""),
            })

    def add_backup(self, entry):
        """One backup attempt (same shape as a panel entry, plus outcome)."""
        usage = entry.get("usage") or {}
        self.data["backups"].append({
            "model": entry.get("model"),
            "promoted": bool(entry.get("ok")),
            "error": _summarize(entry.get("error")),
            "finish_reason": entry.get("finish_reason") or None,
            "truncated": bool(entry.get("truncated")),
            "total_tokens": usage.get("total_tokens"),
            "cost": entry.get("cost"),
            "elapsed": entry.get("elapsed"),
            "text_length": len(entry.get("text") or ""),
        })

    def set_judge(self, per_model, dual_ok, dual_reason, entropy):
        """per_model: list of {model, winner, confidence, repaired,
        attempts, mode, error, finish_reason, cost}."""
        self.data["judge"] = {
            "models": [{
                "model": m.get("model"),
                "winner": m.get("winner"),
                "confidence": m.get("confidence"),
                "repaired": bool(m.get("repaired")),
                "attempts": m.get("attempts"),
                "repair_mode": m.get("mode"),
                "error": _summarize(m.get("error")),
                "finish_reason": m.get("finish_reason") or None,
                "cost": m.get("cost"),
            } for m in per_model],
            "dual_ok": dual_ok,
            "dual_reason": dual_reason,
            "entropy": entropy,
        }

    def set_synth(self, model, ok, error, finish_reason, cost, text_length):
        self.data["synth"] = {"model": model,
                              "ok": bool(ok),
                              "error": _summarize(error),
                              "finish_reason": finish_reason or None,
                              "cost": cost,
                              "text_length": text_length}

    def set_redteam(self, critics, adjudicator):
        """critics: list of {model, ok, repaired, findings, cost};
        adjudicator: {ok, repaired, verdict, confidence, cost}."""
        self.data["redteam"] = {
            "critics": [{
                "model": c.get("model"),
                "ok": bool(c.get("ok")),
                "repaired": bool(c.get("repaired")),
                "findings": c.get("findings"),
                "cost": c.get("cost"),
            } for c in critics],
            "adjudicator": adjudicator,
        }

    def set_verdict(self, text, source):
        self.data["verdict"] = text
        self.data["verdict_source"] = source

    def set_spent(self, spent):
        self.data["spent"] = spent

    # -- output (best-effort, never raises) --

    def write(self):
        """Write the JSON log file. Idempotent; never raises."""
        if self.written:
            return self.path
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            self.data["finished_utc"] = _utc_now().isoformat()
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self.written = True
            return self.path
        except Exception as e:
            print("[thinktank] WARNING: run log write failed (%s); "
                  "continuing without a run log" % e, file=sys.stderr)
            return None
