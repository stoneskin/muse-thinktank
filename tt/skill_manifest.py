"""v0.12 module: tt/skill_manifest.py.

Layer 0: skill manifest standard — schema validation + dependency DAG
resolution. Skills never call each other directly; they declare
requires/provides/depends_on and exchange data through a shared context.

Two gates against circular dependencies:
  1. Static: topological sort at load time, refuse to start on cycles.
  2. Dynamic: execution depth cap as a backstop.
"""

import json
import os

SCHEMA_VERSION = 1

REQUIRED_FIELDS = [
    "name", "version", "domain", "capability",
    "trigger", "input_schema", "depends_on", "provides",
]
REQUIRED_TRIGGER_FIELDS = ["keywords", "intent"]
REQUIRED_PROVIDES_FIELDS = ["output_schema"]


class ManifestError(Exception):
    pass


def validate_manifest(m):
    """Validate a manifest dict. Raises ManifestError on violation."""
    if not isinstance(m, dict):
        raise ManifestError("manifest is not a dict")
    missing = [f for f in REQUIRED_FIELDS if f not in m]
    if missing:
        raise ManifestError("missing fields: %s" % ", ".join(missing))
    t = m["trigger"]
    if not isinstance(t, dict):
        raise ManifestError("trigger must be a dict")
    missing = [f for f in REQUIRED_TRIGGER_FIELDS if f not in t]
    if missing:
        raise ManifestError("trigger missing: %s" % ", ".join(missing))
    if not isinstance(t["keywords"], list) or not t["keywords"]:
        raise ManifestError("trigger.keywords must be a non-empty list")
    p = m["provides"]
    if not isinstance(p, dict):
        raise ManifestError("provides must be a dict")
    missing = [f for f in REQUIRED_PROVIDES_FIELDS if f not in p]
    if missing:
        raise ManifestError("provides missing: %s" % ", ".join(missing))
    if not isinstance(m["depends_on"], list):
        raise ManifestError("depends_on must be a list")
    if not isinstance(m["domain"], list) or not m["domain"]:
        raise ManifestError("domain must be a non-empty list")
    # Deep validation: input_schema and output_schema must be dicts
    # with type/properties structure
    for sf in ("input_schema",):
        s = m.get(sf)
        if s is not None and not isinstance(s, dict):
            raise ManifestError("%s must be a dict" % sf)
    osch = p["output_schema"]
    if not isinstance(osch, dict) or "type" not in osch:
        raise ManifestError("provides.output_schema must be a dict with 'type'")
    if not isinstance(t.get("intent"), str) or not t["intent"]:
        raise ManifestError("trigger.intent must be a non-empty string")
    return True


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    validate_manifest(m)
    m["_path"] = path
    return m


def load_all(skills_dir):
    """Load every manifest.json under skills_dir. Returns {name: manifest}."""
    out = {}
    for entry in sorted(os.listdir(skills_dir)):
        mp = os.path.join(skills_dir, entry, "manifest.json")
        if os.path.isfile(mp):
            m = load_manifest(mp)
            if m["name"] in out:
                raise ManifestError(
                    "duplicate skill name: %s" % m["name"])
            out[m["name"]] = m
    return out


def resolve_order(manifests):
    """Topological sort by depends_on. Raises ManifestError on cycles or
    missing dependencies. Returns execution order (dependencies first)."""
    order = []
    visiting = set()
    visited = set()

    def visit(name, stack):
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join(stack + [name])
            raise ManifestError("circular dependency: %s" % cycle)
        if name not in manifests:
            raise ManifestError(
                "unknown dependency: %s (needed by %s)"
                % (name, stack[-1] if stack else "?"))
        visiting.add(name)
        for dep in manifests[name]["depends_on"]:
            visit(dep, stack + [name])
        visiting.discard(name)
        visited.add(name)
        order.append(name)

    for name in sorted(manifests):
        visit(name, [])
    return order


class SkillContext:
    """Shared context. Skills read/write via get/put only —
    never import or call another skill."""

    def __init__(self):
        self._data = {}
        self._depth = 0
        self.max_depth = 10

    def get(self, key, default=None):
        return self._data.get(key, default)

    def put(self, key, value):
        self._data[key] = value

    def keys(self):
        return list(self._data.keys())
