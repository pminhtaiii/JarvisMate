"""python -m zaic_tools --split public_test --id public_0008 --tool smart_home.get_status --args '{}'
   python -m zaic_tools --split train --apps        # apps and tools of the split's catalog, and whether zaic_tools implements them
   python -m zaic_tools --split public_test --validate submission.jsonl   # schema check of every call (the scorer's rejection rule), nothing executed"""
import argparse, json

from . import ToolEnv, catalog_path, schema_validate
from .apps import TOOLS

ap = argparse.ArgumentParser(description="call one tool on one sample, or list the apps of a split")
ap.add_argument("--split", default="public_test"); ap.add_argument("--root", help="data folder (default: data/ next to the package)")
ap.add_argument("--apps", action="store_true", help="list the split's apps/tools from its catalog")
ap.add_argument("--validate", metavar="SUBMISSION", help="schema-check every tool_calls line of a submission.jsonl against the split's catalog and each sample's installed apps")
ap.add_argument("--id"); ap.add_argument("--tool"); ap.add_argument("--args", default="{}")
a = ap.parse_args()
if a.validate:
    cat = json.load(open(catalog_path(a.split, a.root), encoding="utf-8"))
    lines = bad = 0
    for line in open(a.validate, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line); lines += 1
        try:
            allowed = ToolEnv(a.split, row["id"], a.root).allowed
        except FileNotFoundError:
            print(f"{row['id']}: no state in split {a.split}"); bad += 1; continue
        for i, r in enumerate(schema_validate(row.get("tool_calls") or [], cat, allowed)):
            if not r["ok"]:
                bad += 1; print(f"{row['id']} call {i} {r['name']}: {r['error']}")
    print(f"{lines} lines checked, {bad} schema errors")
elif a.apps:
    cat = json.load(open(catalog_path(a.split, a.root), encoding="utf-8"))
    missing = 0
    for app in cat["apps"]:
        tools = [t["name"] for t in app["tools"]]
        impl = [t for t in tools if t in TOOLS]
        missing += len(tools) - len(impl)
        print(f"{app['id']:<20} {len(impl)}/{len(tools)} tool implemented" + ("" if len(impl) == len(tools) else "   missing: " + ", ".join(t.split('.', 1)[1] for t in tools if t not in TOOLS)))
    print(f"{len(cat['apps'])} apps, {sum(len(x['tools']) for x in cat['apps'])} tools, {missing} not implemented")
else:
    if not (a.id and a.tool):
        ap.error("--id and --tool are required unless --apps")
    print(json.dumps(ToolEnv(a.split, a.id, a.root).call(a.tool, json.loads(a.args)), ensure_ascii=False, indent=1))
