"""v0.13 module: tt/golden_cases.py.

Golden cases: hard regression cases for stock analysis, code review, and
docs. Each case has a fixed input, expected output characteristics, and a
minimum score. Run offline; non-zero exit on regression.

A golden case is NOT a model eval — it pins the harness behavior:
prompt construction, context injection, output parsing, fail-closed paths.
"""

import json
import os
import sys
import threading
import time
import traceback

_DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs",
                            "golden-cases")
GOLDEN_DIR = os.environ.get("GOLDEN_CASES_DIR", _DEFAULT_DIR)


def load_cases(category=None):
    """Load golden cases from docs/golden-cases/<category>/*.json."""
    cases = []
    base = GOLDEN_DIR
    if not os.path.isdir(base):
        print("golden cases dir not found: %s" % base, file=sys.stderr)
        return []
    cats = [category] if category else sorted(os.listdir(base))
    for cat in cats:
        cdir = os.path.join(base, cat)
        if not os.path.isdir(cdir):
            continue
        for fn in sorted(os.listdir(cdir)):
            if fn.endswith(".json"):
                fp = os.path.join(cdir, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        c = json.load(f)
                except (OSError, ValueError) as e:
                    print("golden case unreadable %s: %s" % (fp, e),
                          file=sys.stderr)
                    continue
                c["_category"] = cat
                c["_file"] = fn
                cases.append(c)
    return cases


def check_case(case, result, min_chars=50):
    """Check a harness result against a golden case.

    Returns (passed: bool, details: str). min_chars is the minimum
    output length; short-answer cases can lower it.
    """
    cid = case.get("id", "?")
    expects = case.get("expects", {})

    # 1. Must not crash / must produce output
    if result.get("error"):
        return False, "%s: harness error: %s" % (cid, result["error"])
    text = result.get("text", "")
    if not text or len(text.strip()) < min_chars:
        return False, "%s: empty or trivial output (%d chars)" % (
            cid, len(text))

    # 2. Must contain required keywords (answer_key markers)
    # Case-insensitive to avoid false negatives on capitalization.
    text_low = text.lower()
    keywords = expects.get("must_contain", [])
    missing = [k for k in keywords if k.lower() not in text_low]
    if missing:
        return False, "%s: missing keywords: %s" % (cid, missing[:3])

    # 3. Must NOT contain forbidden patterns (hallucination markers)
    forbidden = expects.get("must_not_contain", [])
    hit = [p for p in forbidden if p.lower() in text_low]
    if hit:
        return False, "%s: forbidden pattern found: %s" % (cid, hit[:3])

    # 4. Minimum score if the case defines a scorer
    min_score = expects.get("min_score")
    if min_score is not None:
        score = result.get("score", 0) or 0
        if score < min_score:
            return False, "%s: score %.1f < min %.1f" % (
                cid, score, min_score)

    return True, "%s: OK" % cid


def run_all(harness_fn, category=None, verbose=False, max_workers=4,
            timeout=300, min_chars=50):
    """Run all golden cases through harness_fn(case) -> result dict.

    harness_fn MUST be thread-safe when max_workers > 1; pass
    max_workers=1 for sequential execution.

    Returns (passed, failed, details). Exits non-zero on any failure
    when called as a script. Runs in parallel via threads, each case
    bounded by `timeout` seconds.
    """
    cases = load_cases(category)
    if not cases:
        print("no golden cases found in %s" % GOLDEN_DIR, file=sys.stderr)
        return 0, 0, []

    def _run_one(case):
        cid = case.get("id", "?")
        try:
            result = harness_fn(case)
        except Exception:
            # System error (config, import, API key) — distinct from
            # a test assertion failure. Full traceback for debugging.
            tb = traceback.format_exc().strip().splitlines()
            tail = tb[-5:] if len(tb) > 5 else tb
            return False, "%s: HARNESS ERROR (not a test failure):\n%s" % (
                cid, "\n".join(tail))
        try:
            return check_case(case, result, min_chars=min_chars)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            tail = tb[-5:] if len(tb) > 5 else tb
            return False, "%s: checker error:\n%s" % (cid, "\n".join(tail))

    passed, failed, details = 0, 0, []
    # Daemon threads + per-case Event: a hung case is reported as TIMEOUT
    # and cannot stall the suite or block process exit. (ThreadPoolExecutor
    # uses non-daemon threads, so a hung worker would hang the process
    # at exit even after shutdown(wait=False).)
    sem = threading.Semaphore(max(1, max_workers))
    slots = {}  # cid -> {"event": Event, "result": (ok, msg) or None}

    def _worker(case, cid):
        with sem:
            try:
                slots[cid]["result"] = _run_one(case)
            except Exception:
                tb = traceback.format_exc().strip().splitlines()
                tail = tb[-5:] if len(tb) > 5 else tb
                slots[cid]["result"] = (
                    False, "%s: worker error:\n%s" % (cid, "\n".join(tail)))
            finally:
                slots[cid]["event"].set()

    for case in cases:
        cid = case.get("id", "?")
        # Deduplicate cids so per-case slots don't collide
        base, n = cid, 2
        while cid in slots:
            cid = "%s#%d" % (base, n)
            n += 1
        case["_slot"] = cid
        slots[cid] = {"event": threading.Event(), "result": None}
        t = threading.Thread(target=_worker, args=(case, cid), daemon=True)
        t.start()

    for case in cases:  # preserves case order in details
        cid = case["_slot"]
        slot = slots[cid]
        if slot["event"].wait(timeout=timeout):
            ok, msg = slot["result"]
        else:
            ok, msg = False, "%s: TIMEOUT after %ds" % (
                case.get("id", "?"), timeout)
        details.append(msg)
        if verbose or not ok:
            print(msg)
        if ok:
            passed += 1
        else:
            failed += 1
    print("golden cases: %d passed, %d failed (%d total)"
          % (passed, failed, len(cases)))
    return passed, failed, details


if __name__ == "__main__":
    # Offline self-check: validate case files are well-formed.
    cases = load_cases()
    bad = 0
    for c in cases:
        if "id" not in c or "prompt" not in c or "expects" not in c:
            print("malformed: %s/%s" % (c["_category"], c["_file"]))
            bad += 1
    print("%d cases, %d malformed" % (len(cases), bad))
    sys.exit(1 if bad else 0)
