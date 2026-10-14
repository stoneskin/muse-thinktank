"""v0.11 module: tt/run_record.py.

Complete versioned JSON trace of a thinktank run. Purpose: auditability,
offline replay, and regression measurement — not just the final text.

Schema version: 1. Never remove fields; only add (with defaults) so old
records stay replayable.
"""

import hashlib
import json
import os
import re
import time

SCHEMA_VERSION = 1

# Fields that must be present for a record to be considered valid.
# Replay fail-closes on missing fields or hash mismatch.
REQUIRED_TOP_FIELDS = [
    "schema_version", "question", "context_hash", "stages",
    "models", "params", "cost", "verdict",
]


def _normalize_floats(o):
    # Floats serialize non-deterministically across platforms; normalize
    # to fixed 6-decimal strings before hashing so a record validates
    # identically everywhere.
    if isinstance(o, float):
        return "%.6f" % o
    if isinstance(o, dict):
        return {k: _normalize_floats(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_normalize_floats(x) for x in o]
    return o


def _sha256_of(obj, schema_version=SCHEMA_VERSION):
    # v1: floats normalized to 6-decimal strings. If a future schema
    # changes normalization, branch on schema_version here so old
    # records keep validating.
    if schema_version == 1:
        obj = _normalize_floats(obj)
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True,
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# Matches ?token=xxx / &key=yyy style credentials in URLs and free text.
_CRED_RE = re.compile(
    r"(?i)(token|api[_-]?key|auth|secret|passwd|password|bearer)[=:][^&\s\"']+"
)

def _redact(obj):
    """Strip secrets / credentials from anything going into the record.

    Two layers: (1) drop dict values whose key name looks like a secret;
    (2) regex-scrub credential patterns inside free-text strings
    (e.g. tokens embedded in URLs in the preamble).
    """
    if isinstance(obj, str):
        obj = _CRED_RE.sub(r"\1=[redacted]", obj)
        if len(obj) > 40 and obj.startswith("sk-"):
            return "[redacted]"
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in ("key", "token", "secret", "password",
                                     "credential", "auth", "bearer")):
                out[k] = "[redacted]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


class RunRecord:
    """Collector. Created at run start, filled as phases complete."""

    def __init__(self, question, context_data=None):
        self.data = {
            "schema_version": SCHEMA_VERSION,
            "question": question,
            "context_hash": (_sha256_of(context_data.get("facts", {}))
                             if context_data else None),
            # v0.11.1: store redacted facts too, not just the hash —
            # replay needs the actual context to restore the reasoning
            # environment (Phase 1 #6).
            "context_facts": (_redact(context_data.get("facts", {}))
                              if context_data else None),
            "context_sources": _redact(
                context_data.get("preamble", "") if context_data else ""),
            "stages": {},
            "models": {},
            "params": {},
            "cost": {"spent": 0.0, "budget": None},
            "verdict": None,
            "errors": [],
            "timestamps": {"started_at": time.time()},
            "code": {},
        }

    def set_params(self, **kw):
        self.data["params"].update(_redact(kw))

    def set_code_info(self, commit=None):
        # Best-effort: record the repo commit so a record is traceable
        # to the exact code that produced it.
        if commit is None:
            try:
                import subprocess
                commit = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=2,
                ).stdout.strip() or None
            except Exception:
                commit = None
        self.data["code"]["commit"] = commit

    def add_model(self, role, model_id, provider="openrouter", **kw):
        self.data["models"][role] = _redact(
            {"id": model_id, "provider": provider, **kw})

    def add_stage(self, name, **kw):
        st = self.data["stages"].setdefault(name, {})
        st.update(_redact(kw))
        st["finished_at"] = time.time()

    def add_error(self, where, message):
        self.data["errors"].append(
            {"where": where, "message": str(message)[:500],
             "at": time.time()})

    def set_verdict(self, verdict, evidence_refs=None):
        self.data["verdict"] = {
            "text": verdict,
            "evidence_refs": evidence_refs or [],
        }
        self.data["timestamps"]["finished_at"] = time.time()

    def add_cost(self, amount):
        self.data["cost"]["spent"] = round(
            self.data["cost"]["spent"] + amount, 6)

    def save(self, path):
        d = dict(self.data)
        d["record_hash"] = _sha256_of(
            {k: v for k, v in d.items() if k != "record_hash"})
        with open(path, "w") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return path


def load_record(path):
    """Load + validate. Returns (record_dict, error_str).

    Fail-closed: missing file, bad JSON, missing required fields, or
    hash mismatch all return an error instead of a partial record.
    """
    if not os.path.exists(path):
        return None, "record file not found: %s" % path
    try:
        with open(path) as f:
            d = json.load(f)
    except (ValueError, OSError) as e:
        return None, "record file unreadable: %s (%s)" % (path, e)
    if not isinstance(d, dict):
        return None, "record is not a JSON object: %s" % path
    missing = [f for f in REQUIRED_TOP_FIELDS if f not in d]
    if missing:
        return None, "record missing required fields: %s" % ", ".join(missing)
    want = d.get("record_hash")
    got = _sha256_of({k: v for k, v in d.items() if k != "record_hash"},
                     schema_version=d.get("schema_version", 1))
    if want != got:
        return None, ("record hash mismatch: file may be corrupted or "
                       "tampered with (want %s, got %s)"
                       % (str(want)[:12], got[:12]))
    return d, None


def replay_summary(record):
    """Offline replay: walk the record, verify internal consistency,
    print a human-readable summary. Makes zero API calls."""
    lines = []
    lines.append("replay: schema v%s" % record.get("schema_version"))
    lines.append("question: %s" % str(record.get("question"))[:120])
    models = record.get("models", {})
    for role, m in models.items():
        lines.append("  %s: %s" % (role, m.get("id")))
    stages = record.get("stages", {})
    for name, st in stages.items():
        n_out = len(st.get("outputs", [])) if isinstance(
            st.get("outputs"), list) else "-"
        lines.append("  stage %s: outputs=%s cost=$%.4f" % (
            name, n_out, st.get("cost", 0) or 0))
    cost = record.get("cost", {})
    lines.append("total spent: $%.4f (budget $%s)" % (
        cost.get("spent", 0), cost.get("budget")))
    errs = record.get("errors", [])
    if errs:
        lines.append("errors: %d" % len(errs))
        for e in errs[:5]:
            lines.append("  [%s] %s" % (e.get("where"), e.get("message")))
    v = record.get("verdict") or {}
    if v.get("text"):
        lines.append("verdict: %s" % str(v["text"])[:200])
    return "\n".join(lines)
