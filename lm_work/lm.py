"""Claude-as-LLM helper for LifeMate public_test.

  python lm.py list [start] [end]        # list sample ids with status and final transcript
  python lm.py show <id>                 # context, history (ASR transcripts), final request, calls so far
  python lm.py tool <name> [<name>...]   # tool schemas
  python lm.py train <regex> [n]         # train examples whose audio_text matches regex (gold calls)
  python lm.py call <id> '<json>'        # json: one call {"name","arguments"} or a list; validated, appended, replayed
  python lm.py undo <id>                 # drop the last appended call (only allowed before 'done')
  python lm.py done <id>                 # mark sample finished (calls may be empty)
  python lm.py build [out]               # replay every sample once, write submission.jsonl

Calls are stored in calls/<id>.json. The env is deterministic, so replaying the recorded list in a fresh ToolEnv
reproduces exactly one session; the final build uses one ToolEnv per sample with that list.
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "data_unz" / "train+public_test"
SPLIT = "public_test"
sys.path.insert(0, str(ROOT / SPLIT))
sys.dont_write_bytecode = True
from zaic_tools import ToolEnv  # noqa: E402

import os  # noqa: E402
import difflib  # noqa: E402
import unicodedata  # noqa: E402

CALLS = HERE / os.environ.get("LM_CALLS", "calls")
CALLS.mkdir(exist_ok=True)
TRANS = json.load(open(HERE.parent / "transcripts_public_test.txt", encoding="utf-8"))


def _opt(name):
    p = HERE / name
    return json.load(open(p, encoding="utf-8")) if os.environ.get("LM_ASR2") and p.is_file() else {}


NBEST = _opt("asr_nbest.json")
PASS2 = _opt("asr_pass2.json")


def phon(s):
    """Rough Vietnamese-style phonetic key: lets 'Wantaboo' meet 'Watanabe', 'Kanner' meet 'Ngân'-like spellings."""
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z ]", " ", s)
    out = []
    for w in s.split():
        for a, b in (("ngh", "ng"), ("ph", "f"), ("th", "t"), ("tr", "c"), ("ch", "c"), ("gh", "g"), ("gi", "z"),
                     ("qu", "kw"), ("q", "k"), ("c", "k"), ("d", "z"), ("r", "z"), ("j", "z"), ("x", "s")):
            if w.startswith(a):
                w = b + w[len(a):]
                break
        for a, b in (("ck", "k"), ("c", "k"), ("w", "u"), ("y", "i"), ("oo", "u"), ("ee", "i"), ("ph", "f"), ("th", "t")):
            w = w.replace(a, b)
        w = re.sub(r"(?<=[aeiou])r(?=[^aeiou]|$)", "", w)   # English post-vocalic r is silent for Vietnamese ears
        w = re.sub(r"(?<=[aeiou])h(?=[^aeiou]|$)", "", w)
        w = re.sub(r"(?<!n)[dg]$", "t", w)
        w = re.sub(r"(.)\1+", r"\1", w)
        out.append(w)
    return " ".join(out)


def phon_hints(texts, names, thr=0.62):
    """For each known entity name, best matching same-length word window in any ASR hypothesis."""
    hints = []
    for name in names:
        kn, nw = phon(name), len(name.split())
        if len(kn.replace(" ", "")) < 5:
            continue
        best = (0, "")
        for t in texts:
            ws = t.split()
            for L in {max(1, nw - 1), nw, nw + 1}:
                for s in range(0, max(1, len(ws) - L + 1)):
                    span = " ".join(ws[s:s + L])
                    r = difflib.SequenceMatcher(None, phon(span).replace(" ", ""), kn.replace(" ", "")).ratio()
                    if r > best[0]:
                        best = (r, span)
        if best[0] >= thr and phon(best[1]) != kn:
            hints.append(f"'{best[1]}' ~ '{name}' ({best[0]:.2f})")
    return hints


def items():
    return [json.loads(l) for l in open(ROOT / SPLIT / f"{SPLIT}.jsonl", encoding="utf-8") if l.strip()]


def item(i):
    for it in items():
        if it["id"] == i:
            return it
    raise SystemExit(f"no sample {i}")


def catalog(split=SPLIT):
    cat = json.load(open(ROOT / split / f"{split}_tools_catalog.json", encoding="utf-8"))
    return {t["name"]: t for a in cat["apps"] for t in a["tools"]}


def rec_path(i):
    return CALLS / f"{i}.json"


def load_rec(i):
    p = rec_path(i)
    return json.load(open(p, encoding="utf-8")) if p.is_file() else {"calls": [], "done": False}


def save_rec(i, rec):
    json.dump(rec, open(rec_path(i), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def d(v):
    return json.dumps(v, ensure_ascii=False)


def replay(i, calls):
    env = ToolEnv(SPLIT, i, root=str(ROOT))
    res = [env.call(c["name"], c.get("arguments", {})) for c in calls]
    return env, res


NAME_KEYS = {"name", "title", "display_name", "label", "contact_name", "chat_name", "restaurant", "product", "symbol",
             "station", "place", "location", "artist", "track", "program", "provider", "merchant", "beneficiary_name"}


def _names(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k in NAME_KEYS or k.endswith("_name")) and 1 < len(v) <= 60:
                out.append(v)
            else:
                _names(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _names(v, out)
    return out


def cmd_list(a):
    its = items()
    s = int(a[0]) if a else 0
    e = int(a[1]) if len(a) > 1 else len(its)
    for it in its[s:e]:
        r = load_rec(it["id"])
        st = "DONE" if r["done"] else ("..." if r["calls"] else "   ")
        print(f"{it['id']} {st} {TRANS.get(it['audio'], '?')}")


def cmd_show(a):
    it = item(a[0])
    c = it["context"]
    print("time:", c["current_time"], c["timezone"], "| location:", d(c["location"]))
    print("profile:", d(c["user_profile"]))
    print("apps:", ", ".join(c["installed_apps"]))
    for t in it.get("history", []):
        if t["role"] == "user":
            print("USER:", TRANS.get(t.get("audio"), "?"))
        else:
            print("ASSISTANT:", t.get("text", ""))
            for k, call in enumerate(t.get("tool_calls", []) or []):
                print("   call:", call["name"], d(call.get("arguments", {})))
                tr = (t.get("tool_results") or [None] * 99)
                if k < len(tr) and tr[k] is not None:
                    print("   result:", d(tr[k])[:1500])
    print("=== FINAL REQUEST:", TRANS.get(it["audio"], "?"))
    nb = NBEST.get(it["audio"], {}).get("nbest", [])
    for k, (t, s) in enumerate(nb):
        print(f"   ASR n-best #{k + 1} ({s}): {t}")
    r = load_rec(it["id"])
    names = []
    if r["calls"]:
        env, res = replay(it["id"], r["calls"])
        for call, out in zip(r["calls"], res):
            print(" [done] ", call["name"], d(call.get("arguments", {})), "->", d(out)[:1500])
            if env.kind(call["name"]) == "read":
                names += _names(out)
        # pass 2 = re-decode with names from THIS run's read results as Whisper prompt (computed offline from the
        # same reads); shown only once those reads have been made here
        p2 = PASS2.get(it["audio"])
        if p2 and set(p2["vocab"]) <= set(names):
            print("   ASR pass-2 (prompted with names from your reads):", p2["text"])
        texts = [TRANS.get(it["audio"], "")] + [t for t, _ in nb] + ([p2["text"]] if p2 else [])
        h = phon_hints(texts, list(dict.fromkeys(names)))
        if h:
            print("   phonetic name matches:", "; ".join(h))
    print("status:", "DONE" if r["done"] else "open")


def cmd_tool(a):
    cat = catalog()
    for n in a:
        if n.endswith(".*") or "." not in n:
            names = [k for k in cat if k.startswith(n.rstrip("*").rstrip(".") + ".")]
        else:
            names = [n]
        for k in names:
            t = cat.get(k)
            if not t:
                print("unknown tool", k)
                continue
            print(f"## {k} [{t.get('kind')}] {t.get('description', '')}")
            print("   params:", d(t.get("parameters", {})))
            if t.get("returns"):
                print("   returns:", t["returns"])


def cmd_train(a):
    pat = re.compile(a[0], re.I)
    n = int(a[1]) if len(a) > 1 else 8
    shown = 0
    for l in open(ROOT / "train" / "train.jsonl", encoding="utf-8"):
        it = json.loads(l)
        if not pat.search(it.get("audio_text", "")):
            continue
        hist = " | ".join(("U: " + t.get("audio_text", "")) if t["role"] == "user" else ("A: " + t.get("text", "")[:100]) for t in it.get("history", []))
        print(f"## {it['id']} {it['context']['current_time']} {('HIST: ' + hist) if hist else ''}")
        print("   Q:", it["audio_text"])
        lab = it["label"]
        for k, call in enumerate(lab["tool_calls"]):
            print("   ->", call["name"], d(call["arguments"]), "=>", d(lab["tool_results"][k])[:300])
        if not lab["tool_calls"]:
            print("   -> []")
        shown += 1
        if shown >= n:
            break


def cmd_call(a):
    i, payload = a[0], json.loads(a[1])
    new = payload if isinstance(payload, list) else [payload]
    rec = load_rec(i)
    if rec["done"]:
        raise SystemExit("sample already DONE; refusing to add calls")
    env, _ = replay(i, rec["calls"])
    for c in new:
        c = {"name": c["name"], "arguments": c.get("arguments", {})}
        v = env.validate(c["name"], c["arguments"])
        if not v.get("ok"):
            print("REJECTED (not recorded):", c["name"], d(c["arguments"]), "->", v.get("error"))
            break
        out = env.call(c["name"], c["arguments"])
        rec["calls"].append(c)
        save_rec(i, rec)
        print(c["name"], d(c["arguments"]), "->", d(out)[:4000])


def cmd_undo(a):
    rec = load_rec(a[0])
    if rec["done"]:
        raise SystemExit("DONE; cannot undo")
    if rec["calls"]:
        print("removed", d(rec["calls"].pop()))
    save_rec(a[0], rec)


def cmd_done(a):
    for i in a:
        rec = load_rec(i)
        rec["done"] = True
        save_rec(i, rec)
        print(i, "DONE", len(rec["calls"]), "calls")


def cmd_build(a):
    out = Path(a[0]) if a else HERE.parent / "submission.jsonl"
    n = missing = 0
    with open(out, "w", encoding="utf-8") as f:
        for it in items():
            rec = load_rec(it["id"])
            if not rec["done"]:
                missing += 1
            env = ToolEnv(SPLIT, it["id"], root=str(ROOT))
            for c in rec["calls"]:
                env.call(c["name"], c["arguments"])
            f.write(json.dumps({"id": it["id"], "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} lines -> {out} ({missing} not marked DONE)")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    globals()["cmd_" + cmd](rest)
