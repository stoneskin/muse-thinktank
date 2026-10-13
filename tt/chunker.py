"""v0.8 module: tt/chunker.py -- diff chunking (Map-Reduce).

Split a large diff by file into ~3k-token chunks, each reviewed independently.
"""

import re

# unified diff file header: diff --git a/path b/path
DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.M)


def split_diff_by_file(diff_text, max_tokens=3000):
    """Split diff by file. Each chunk ~max_tokens (estimated at 4 chars/token).
    Returns [(filename, chunk_text), ...]. Oversized single files are split by hunk.
    """
    chunks = []
    if not diff_text:
        return chunks
    # find all file header positions
    matches = list(DIFF_FILE_RE.finditer(diff_text))
    if not matches:
        # not a standard diff; treat as one chunk (hard-split if oversized)
        if len(diff_text) // 4 <= max_tokens:
            return [("single", diff_text)]
        chunk_chars = max_tokens * 4
        for idx in range(0, len(diff_text), chunk_chars):
            chunks.append((f"part-{idx//chunk_chars}", diff_text[idx:idx+chunk_chars]))
        return chunks
    for mi, m in enumerate(matches):
        fname = m.group(1)
        start = m.start()
        end = matches[mi + 1].start() if mi + 1 < len(matches) else len(diff_text)
        content = diff_text[start:end]
        est = len(content) // 4
        if est <= max_tokens:
            chunks.append((fname, content))
        else:
            # split by hunk
            hunks = re.split(r"(?=^@@ )", content, flags=re.M)
            cur, cur_est = [], 0
            for h in hunks:
                h_est = len(h) // 4
                if cur and cur_est + h_est > max_tokens:
                    chunks.append((f"{fname}#hunk", "".join(cur)))
                    cur, cur_est = [], 0
                cur.append(h)
                cur_est += h_est
            if cur:
                chunks.append((f"{fname}#hunk", "".join(cur)))
    return chunks
