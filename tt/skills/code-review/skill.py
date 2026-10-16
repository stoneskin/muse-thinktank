"""Seed skill: code-review.

Two modes, one skill:
- PR mode (pr_url given): fetch a GitHub PR diff and structure review
  context. Read-only: never comments, merges, or modifies anything.
- Design mode (no pr_url): the review target is a design doc / repo
  scaffold, not a diff. Emits the design-review rubric into shared
  context so the run record shows what standard the panel was held to.

Error policy: a missing pr_url degrades to design mode -- it means the
review target is a design, not a failure. A malformed pr_url or a
diff-fetch failure still raises: fail-closed, the panel must not
review a PR it cannot see.
"""

import re
import shutil
import subprocess
import urllib.request


# Design-review rubric (v1.1): the four lenses a design review must cover.
# Kept as data so the run record shows the standard, not just prose.
DESIGN_RUBRIC = {
    "self_consistency": (
        "目标 vs 机制有没有打架: 每个设计目标反问一句\"这个机制真的"
        "服务于这个目标吗\"; private/public 假设是否一致; \"二期再做\""
        "的承诺与现实更新频率是否冲突"
    ),
    "acceptance_criteria": (
        "每个设计目标必须可证伪: 配 Given/When/Then 验收标准."
        "\"5 分钟上手\"这类目标没有验收标准就是空话"
    ),
    "decision_review": (
        "每个关键决策 (D1..Dn) 逐个给 keep / 修改 / 砍掉, 并说理由."
        "决策不是越多越好, 互相打架的决策必须当场二选一"
    ),
    "risk_grading": (
        "风险分三级: 硬冲突 (必须改, 否则目标落空) / 张力 (有代价, "
        "给出最低成本的缓解) / 可接受 (记录, 不 block)"
    ),
}


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


def _run_pr_mode(ctx, pr_url, focus):
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
        "mode": "pr",
        "pr_url": pr_url,
        "repo": "%s/%s" % (owner, repo),
        "pr_number": int(num),
        "files_changed": len(files),
        "diff_stat": {"files": files[:50]},
        "diff_chars": len(diff),
        "diff_source": source,
        "focus": focus,
    }
    # Don't dump the whole diff into ctx; panel fetches via --pr-diff.
    # Keep a truncated preview for the record.
    out["diff_preview"] = diff[:2000]
    ctx.put("code-review", out)
    return out


def _run_design_mode(ctx, focus):
    out = {
        "mode": "design-review",
        "pr_url": None,
        "focus": focus,
        "note": ("no pr_url supplied: reviewing a design doc / repo "
                 "scaffold, not a diff"),
        "rubric": DESIGN_RUBRIC,
        "guide": "docs/code-review-guide.md",
    }
    ctx.put("code-review", out)
    return out


def run(ctx):
    pr_url = ctx.get("pr_url")
    focus = ctx.get("focus", "")
    if pr_url:
        return _run_pr_mode(ctx, pr_url, focus)
    return _run_design_mode(ctx, focus)
