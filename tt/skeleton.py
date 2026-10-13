"""v0.9 module: tt/skeleton.py -- diff skeleton extraction (pipeline step 1).

Extract structured facts from a diff, no bug hunting:
- added/removed/modified functions and classes
- import additions/removals
- export (__all__, module.exports, etc.) changes
- one-line intent (model-supplemented; deterministic extraction only here)
"""

import re

# function definitions: def name( / class Name / function name( / const name = (
FUNC_RE = re.compile(r"^[+-]\s*(?:def\s+(\w+)|class\s+(\w+)|function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)", re.M)
IMPORT_RE = re.compile(r"^[+-]\s*(?:import\s+(.+?)|from\s+(\S+)\s+import|require\(['\"](.+?)['\"]\))", re.M)


def extract_skeleton(diff_text, filename):
    """Extract skeleton from a single file's diff. Returns dict."""
    added_funcs = set()
    removed_funcs = set()
    added_imports = set()
    removed_imports = set()

    for m in FUNC_RE.finditer(diff_text):
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if not name:
            continue
        # check + or -
        line_start = diff_text.rfind("\n", 0, m.start()) + 1
        sign = diff_text[line_start] if line_start < len(diff_text) else ""
        if sign == "+":
            added_funcs.add(name)
        elif sign == "-":
            removed_funcs.add(name)

    for m in IMPORT_RE.finditer(diff_text):
        imp = (m.group(1) or m.group(2) or m.group(3) or "").strip()[:80]
        if not imp:
            continue
        line_start = diff_text.rfind("\n", 0, m.start()) + 1
        sign = diff_text[line_start] if line_start < len(diff_text) else ""
        if sign == "+":
            added_imports.add(imp)
        elif sign == "-":
            removed_imports.add(imp)

    return {
        "file": filename,
        "added_funcs": sorted(added_funcs),
        "removed_funcs": sorted(removed_funcs),
        "added_imports": sorted(added_imports),
        "removed_imports": sorted(removed_imports),
    }


def format_skeleton(skeletons):
    """Format multi-file skeletons as text for the model."""
    lines = ["=== CODEBASE SKELETON (global context) ==="]
    for sk in skeletons:
        lines.append(f"\n## {sk['file']}")
        if sk["added_funcs"]:
            lines.append(f"  +funcs: {', '.join(sk['added_funcs'][:20])}")
        if sk["removed_funcs"]:
            lines.append(f"  -funcs: {', '.join(sk['removed_funcs'][:20])}")
        if sk["added_imports"]:
            lines.append(f"  +imports: {', '.join(sk['added_imports'][:10])}")
        if sk["removed_imports"]:
            lines.append(f"  -imports: {', '.join(sk['removed_imports'][:10])}")
    lines.append("\n=== END SKELETON ===")
    return "\n".join(lines)
