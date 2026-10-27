"""v0.4 module: tt/transport.py."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from .util import log

API = "https://openrouter.ai/api/v1/chat/completions"

PR_DIFF_CAP = 12000  # max chars of PR diff injected into prompt


def fetch_pr_diff(pr_url):
    """v0.4: fetch a public GitHub PR diff and return it as text.

    Accepts https://github.com/{owner}/{repo}/pull/{number} (with or
    without trailing path). Uses the .diff endpoint — no auth needed
    for public repos. Returns None on any failure (fail-open: the
    review just runs without the diff).
    """
    import re
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url.strip())
    if not m:
        log("fetch_pr_diff: not a GitHub PR URL: %s" % pr_url[:80])
        return None
    owner, repo, number = m.groups()
    diff_url = "https://github.com/%s/%s/pull/%s.diff" % (owner, repo, number)
    try:
        req = urllib.request.Request(
            diff_url, headers={"User-Agent": "muse-thinktank/0.4",
                               "Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log("fetch_pr_diff failed (%s): %s" % (diff_url, exc))
        return None
    if len(text) > PR_DIFF_CAP:
        text = text[:PR_DIFF_CAP] + "\n...[truncated]"
    log("PR diff fetched: %d chars from %s/%s#%s"
        % (len(text), owner, repo, number))
    return text


def api_key():
    # Try custom.openrouter credential surrogate first, fall back to env var
    try:
        import sys
        sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
        from dynamic_credentials import dynamic_credential_entry
        entry = dynamic_credential_entry("custom.openrouter", "access_token")
        surrogate = str(entry["surrogate"]).strip()
        if surrogate:
            return surrogate
    except Exception:
        pass
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("error: OPENROUTER_API_KEY is not set and custom.openrouter credential not found", file=sys.stderr)
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


def _is_permanent_error(error):
    """HTTP 401/403/404 are permanent: retrying cannot help (bad key,
    forbidden, or the model id no longer exists on the router)."""
    return (error or "").startswith(("HTTP 401", "HTTP 403", "HTTP 404"))


def health_check(models, key, timeout=20, attempts=3):
    """Lightweight ping per model before the panel.
    Returns (alive, spent, details) where details is one dict per model:
    {model, ok, error, finish_reason, elapsed, cost, attempts}.
    A model that errors or returns empty is dropped for this run.
    Note: max_tokens must be generous (>=50) -- some free models return
    empty with finish_reason=length when the token budget is tiny.
    v0.17: details used to be discarded (only "empty response" was
    logged), which made provider-side failures (e.g. an HTTP 404 from a
    router) indistinguishable from plain empty replies in post-mortems.
    v0.18: transient failures (empty reply, network error, 429/5xx)
    retry up to `attempts` times with 1s/2s backoff -- a single empty
    ping from a flaky free model no longer kills the whole run
    (2026-10-27: both panel models failed one ping, then answered
    fine minutes later). Permanent errors (401/403/404) still drop
    immediately with no retry.
    """
    alive, spent, details = [], 0.0, []
    for m in models:
        last = None
        tried = 0
        for attempt in range(1, attempts + 1):
            tried = attempt
            r = chat(m, [{"role": "user",
                          "content": "Reply with the single word: ok"}],
                     50, 0.0, timeout, key)
            spent += r["cost"]
            last = r
            if not r["error"] and bool(r["text"].strip()):
                alive.append(m)
                break
            if _is_permanent_error(r["error"]):
                break
            if attempt < attempts:
                log("health-check: %s retry %d/%d (%s)"
                    % (m, attempt, attempts - 1,
                       r["error"] or "empty response"))
                time.sleep(attempt)
        r = last
        ok = r is not None and not r["error"] and bool(r["text"].strip())
        if not ok:
            log("health-check: %s unavailable (%s), dropped this round"
                % (m, r["error"] or "empty response"))
        details.append({"model": m, "ok": ok,
                        "error": r["error"],
                        "finish_reason": r["finish_reason"],
                        "elapsed": r["elapsed"], "cost": r["cost"],
                        "attempts": tried})
    return alive, spent, details
