"""v0.4 module: tt/transport.py."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from .util import log

API = "https://openrouter.ai/api/v1/chat/completions"

def api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        raise SystemExit(2)
    return key


def chat(model, messages, max_tokens, temperature, timeout, key):
    """One chat completion. Returns dict(text, usage, cost, error, elapsed,
    truncated, finish_reason)."""
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "muse-thinktank/0.1",
                 "Authorization": "Bearer " + key})
    t0 = time.time()

    def fail(reason):
        return {"text": "", "usage": {}, "cost": 0.0, "error": reason,
                "elapsed": time.time() - t0, "truncated": False,
                "finish_reason": ""}

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        return fail("HTTP %d: %s" % (exc.code, body))
    except Exception as exc:
        return fail("network: %s" % exc)
    err = data.get("error")
    if err:
        return fail("API: %s" % json.dumps(err)[:300])
    choices = data.get("choices") or []
    text = ""
    finish_reason = ""
    if choices:
        text = (choices[0].get("message", {}).get("content") or "").strip()
        finish_reason = choices[0].get("finish_reason") or ""
    usage = data.get("usage") or {}
    try:
        cost = float(usage.get("cost") or 0)
    except (ValueError, TypeError):
        cost = 0.0
    return {"text": text, "usage": usage, "cost": cost, "error": None,
            "elapsed": time.time() - t0,
            "truncated": finish_reason == "length",
            "finish_reason": finish_reason}


def free_ids(state_path):
    """Exact verified-free ids from a models.py scan report (fresh or cached)."""
    report = None
    if state_path and os.path.exists(state_path):
        try:
            report = json.load(open(state_path))
            age = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromisoformat(report["checked_at"]))
            if age > dt.timedelta(hours=24) or "free" not in report:
                report = None
        except (ValueError, KeyError, OSError):
            report = None
    if report is None:
        req = urllib.request.Request(CATALOG,
                                     headers={"User-Agent": "muse-thinktank/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            entries = json.load(resp).get("data", [])

        def z(v):
            try:
                return float(v) == 0
            except (ValueError, TypeError):
                return False

        free = []
        for m in entries:
            pr = m.get("pricing") or {}
            if z(pr.get("prompt")) and z(pr.get("completion")):
                free.append(m["id"])
        return set(free)
    return set(m["id"] for m in report["free"])


def resolve_free(model_id, known):
    """Fail-closed: exact verified-free id, or :free auto-correct with warning,
    else refuse. A missing :free suffix silently routes to the PAID variant."""
    model_id = (model_id or "").strip()
    if model_id in known:
        return model_id
    suffixed = model_id if model_id.endswith(":free") else model_id + ":free"
    if suffixed in known:
        log("WARNING: '%s' is not verified-free; using '%s'. "
            "Calling '%s' directly would use the PAID variant."
            % (model_id, suffixed, model_id))
        return suffixed
    raise SystemExit("error: '%s' is not a verified-free model id. "
                     "Refusing: calling it could incur charges." % model_id)


def health_check(models, key, timeout=20):
    """Lightweight ping per model before the panel. Returns (alive, spent).
    A model that errors or returns empty is dropped for this run.
    Note: max_tokens must be generous (>=50) -- some free models return
    empty with finish_reason=length when the token budget is tiny."""
    alive, spent = [], 0.0
    for m in models:
        r = chat(m, [{"role": "user",
                      "content": "Reply with the single word: ok"}],
                 50, 0.0, timeout, key)
        spent += r["cost"]
        if not r["error"] and r["text"].strip():
            alive.append(m)
        else:
            log("health-check: %s unavailable (%s), dropped this round"
                % (m, r["error"] or "empty response"))
    return alive, spent
