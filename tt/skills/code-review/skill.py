"""Seed skill: code-review.

Fetches a GitHub PR diff and structures review context. Read-only:
never comments, merges, or modifies anything.
"""

import re
import shutil
import subprocess
import json
import urllib.request


def _diff_via_gh(owner, repo, num):
    r = subprocess.run(
        ["gh", "pr", "diff", num, "--repo", "%s/%s" % (owner, repo)],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError("gh pr diff failed: %s" % r.stderr[:200])
    return r.stdout


def _diff_via_api(owner, repo, num):
    # Fallback when gh CLI is missing: public GitHub API, no auth needed
    # for public repos.
    url = ("https://api.github.com/repos/%s/%s/pulls/%s"
           % (owner, repo, num))
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github.v3.diff",
                      "User-Agent": "muse-thinktank"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError("GitHub API diff fetch failed: %s" % e)


def run(ctx):
    pr_url = ctx.get("pr_url")
    if not pr_url:
        raise ValueError("code-review: ctx missing 'pr_url'")
    m = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        raise ValueError("code-review: pr_url must be a GitHub PR URL")
    owner, repo, num = m.groups()

    if shutil.which("gh"):
        diff = _diff_via_gh(owner, repo, num)
        source = "gh"
    else:
        diff = _diff_via_api(owner, repo, num)
        source = "api"
    # Parse "diff --git a/<path> b/<path>" -> <path>
    files = set()
    for l in diff.splitlines():
        if l.startswith("diff --git "):
            parts = l.split(" ")
            if len(parts) >= 4 and parts[2].startswith("a/"):
                files.add(parts[2][2:])
    files = sorted(files)
    out = {
        "pr_url": pr_url,
        "repo": "%s/%s" % (owner, repo),
        "pr_number": int(num),
        "files_changed": len(files),
        "diff_stat": {"files": files[:50]},
        "diff_chars": len(diff),
        "diff_source": source,
        "focus": ctx.get("focus", ""),
    }
    # Don't dump the whole diff into ctx; panel fetches via --pr-diff.
    # Keep a truncated preview for the record.
    out["diff_preview"] = diff[:2000]
    ctx.put("code-review", out)
    return out
