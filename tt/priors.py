"""v0.5 module: tt/priors.py.

Public benchmark priors for model selection. Two keyless sources:

1. LMArena leaderboard (HuggingFace public dataset, CC-BY-4.0):
   stated preference from blind human votes, per-category ratings.
2. OpenRouter /api/v1/models (public, no key):
   model catalog with pricing, context, and benchmark scores.

These are PRIORS, not replacements for task-specific testing.
Funnel: OpenRouter usage filters out unstable models ->
         LMArena gives initial capability ranking ->
         own v1/v3 scores override everything.
"""

import json
import os
import time
import urllib.request

from .util import log

# LMArena public dataset via HuggingFace datasets-server (no key needed)
ARENA_API = ("https://datasets-server.huggingface.co/rows"
             "?dataset=lmarena-ai/leaderboard-dataset"
             "&config=%s&split=latest&length=100")

# OpenRouter public model catalog (no key needed)
OR_MODELS_API = "https://openrouter.ai/api/v1/models"

CACHE_TTL = 6 * 3600  # 6 hours

# Category -> thinktank use case mapping
ARENA_CATEGORIES = ("text", "webdev", "agent", "search")


def _cache_path(name):
    d = os.path.expanduser("~/.cache/muse-thinktank")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "priors-%s.json" % name)


def _fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "muse-thinktank"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _cached_fetch(name, url):
    """Fetch with 6h file cache. Returns (data, from_cache)."""
    p = _cache_path(name)
    if os.path.exists(p):
        try:
            with open(p) as f:
                cached = json.load(f)
            if time.time() - cached.get("_fetched_at", 0) < CACHE_TTL:
                return cached["data"], True
        except (ValueError, KeyError, OSError):
            pass
    data = _fetch_json(url)
    try:
        with open(p, "w") as f:
            json.dump({"_fetched_at": time.time(), "data": data}, f)
    except OSError:
        pass
    return data, False


def fetch_arena(category="text"):
    """Returns {model_name: rating} for one LMArena category."""
    if category not in ARENA_CATEGORIES:
        raise ValueError("unknown arena category: %s" % category)
    data, cached = _cached_fetch("arena-" + category,
                                 ARENA_API % category)
    out = {}
    for row in data.get("rows", []):
        r = row.get("row", {})
        name = r.get("model_name")
        rating = r.get("rating")
        if name and isinstance(rating, (int, float)):
            # keep the best rating if duplicated
            if name not in out or rating > out[name]:
                out[name] = rating
    log("arena/%s: %d models%s" % (category, len(out),
                                   " (cached)" if cached else ""))
    return out


def fetch_openrouter_models():
    """Returns {model_id: info} from OpenRouter public catalog."""
    data, cached = _cached_fetch("or-models", OR_MODELS_API)
    out = {}
    for m in data.get("data", []):
        mid = m.get("id")
        if mid:
            out[mid] = {
                "pricing": m.get("pricing", {}),
                "context_length": m.get("context_length"),
                "per_request_limits": m.get("per_request_limits"),
            }
    log("openrouter: %d models%s" % (len(out),
                                     " (cached)" if cached else ""))
    return out


def normalize_scores(ratings):
    """Min-max normalize ratings to 0.0-1.0."""
    if not ratings:
        return {}
    vals = list(ratings.values())
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return {k: 1.0 for k in ratings}
    return {k: (v - lo) / (hi - lo) for k, v in ratings.items()}


def build_priors(categories=("text", "webdev", "agent")):
    """Build prior scores from public sources.

    Returns {openrouter_model_id: 0.0-1.0}. Arena model names don't
    always match OpenRouter ids exactly; we do best-effort matching
    on the slug portion after '/'.
    """
    priors = {}
    for cat in categories:
        try:
            ratings = normalize_scores(fetch_arena(cat))
        except Exception as e:
            log("arena/%s fetch failed: %s" % (cat, e))
            continue
        for name, score in ratings.items():
            # arena names like "gpt-5", "claude-opus-4-6"; try to match
            # against OpenRouter ids containing the slug
            slug = name.lower().replace(" ", "-")
            # store under arena name; caller maps to OR ids
            key = "arena:" + slug
            priors[key] = max(priors.get(key, 0), score)
    log("priors built: %d entries" % len(priors))
    return priors


def match_priors_to_models(priors, model_ids):
    """Best-effort match arena priors to OpenRouter model ids.

    Returns {model_id: 0.0-1.0}; unmatched models default to 0.5
    (neutral prior -- public data says nothing about them).
    """
    out = {}
    for mid in model_ids:
        slug = mid.split("/")[-1].lower().replace(":free", "").replace("-", "")
        best, best_score = None, 0
        for key, score in priors.items():
            arena_slug = key[6:].replace("-", "")
            if arena_slug and (arena_slug in slug or slug in arena_slug):
                if score > best_score:
                    best, best_score = key, score
        out[mid] = best_score if best else 0.5
    return out


if __name__ == "__main__":
    import sys
    priors = build_priors()
    models = sys.argv[1:] or []
    if models:
        matched = match_priors_to_models(priors, models)
        print(json.dumps(matched, indent=2, ensure_ascii=False))
    else:
        # dump top 20 arena/text as sample
        top = sorted(
            ((k[6:], v) for k, v in priors.items() if k.startswith("arena:")),
            key=lambda x: -x[1])[:20]
        for name, score in top:
            print("%-40s %.3f" % (name, score))
