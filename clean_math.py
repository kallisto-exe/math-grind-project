#!/usr/bin/env python3
"""Math-notation cleanup pipeline (LLM-assisted, via the workflow harness).

  prep   -> split every cleanable item (pool questions, sample-exam questions,
            section intros) into batch files under WORK/in/bNNN.json
  merge  -> read cleaned batch files from WORK/out/bNNN.json and write the
            reconstructed LaTeX back into the source JSON (math fields only).

A separate multi-agent workflow reads WORK/in/bNNN.json and writes the cleaned
WORK/out/bNNN.json (each agent owns one batch -> safe parallelism, no conflicts).

Each item carries a stable `key` so merge can route it back:
  pool:<relpath>      -> questions/<relpath>     (fields: question, explanation, answer)
  exam:<i>:<n>        -> data/exams.json          (fields: question, options)
  intro:<topic>       -> data/learn.json[topic]   (field:  intro)
"""
import json, os, glob, sys, math

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("CLEAN_WORK", "/tmp/finan_clean")
BATCH = int(os.environ.get("CLEAN_BATCH", "25"))


def prep():
    items = []
    # pool questions (free response: question / explanation / answer)
    for path in sorted(glob.glob(os.path.join(ROOT, "questions", "**", "*.json"), recursive=True)):
        if os.path.basename(path) == "index.json":
            continue
        rel = os.path.relpath(path, os.path.join(ROOT, "questions"))
        q = json.load(open(path))
        items.append({"key": f"pool:{rel}", "kind": "pool",
                      "question": q.get("question", ""), "explanation": q.get("explanation", ""),
                      "answer": q.get("answer", "")})
    # sample-exam questions (question + options; do NOT touch the answer letter)
    exams = json.load(open(os.path.join(ROOT, "data", "exams.json")))["exams"]
    for i, ex in enumerate(exams):
        for q in ex["questions"]:
            items.append({"key": f"exam:{i}:{q['n']}", "kind": "exam",
                          "question": q["question"], "options": q["options"]})
    # section intros
    learn = json.load(open(os.path.join(ROOT, "data", "learn.json")))
    for topic, c in learn.items():
        if c.get("intro"):
            items.append({"key": f"intro:{topic}", "kind": "intro", "intro": c["intro"]})

    indir = os.path.join(WORK, "in")
    if os.path.exists(WORK):
        import shutil
        shutil.rmtree(WORK)
    os.makedirs(indir)
    os.makedirs(os.path.join(WORK, "out"))
    n = math.ceil(len(items) / BATCH)
    for b in range(n):
        chunk = items[b * BATCH:(b + 1) * BATCH]
        json.dump(chunk, open(os.path.join(indir, f"b{b:03d}.json"), "w"), ensure_ascii=False, indent=2)
    print(f"prep: {len(items)} items -> {n} batches of {BATCH} in {indir}")
    print(f"  pool={sum(1 for x in items if x['kind']=='pool')} "
          f"exam={sum(1 for x in items if x['kind']=='exam')} "
          f"intro={sum(1 for x in items if x['kind']=='intro')}")
    print(f"BATCHES={n}")


def merge():
    outdir = os.path.join(WORK, "out")
    cleaned = {}
    files = sorted(glob.glob(os.path.join(outdir, "b*.json")))
    bad = 0
    for f in files:
        try:
            for it in json.load(open(f)):
                cleaned[it["key"]] = it
        except Exception as e:
            bad += 1
            print(f"  WARN: could not read {f}: {e}")
    print(f"merge: loaded {len(cleaned)} cleaned items from {len(files)} batch files ({bad} unreadable)")

    applied = {"pool": 0, "exam": 0, "intro": 0}
    # pool
    for path in glob.glob(os.path.join(ROOT, "questions", "**", "*.json"), recursive=True):
        if os.path.basename(path) == "index.json":
            continue
        rel = os.path.relpath(path, os.path.join(ROOT, "questions"))
        it = cleaned.get(f"pool:{rel}")
        if not it:
            continue
        q = json.load(open(path))
        for fld in ("question", "explanation", "answer"):
            if isinstance(it.get(fld), str) and it[fld].strip():
                q[fld] = it[fld]
        json.dump(q, open(path, "w"), ensure_ascii=False, indent=2)
        applied["pool"] += 1
    # exams
    exams_path = os.path.join(ROOT, "data", "exams.json")
    exdata = json.load(open(exams_path))
    for i, ex in enumerate(exdata["exams"]):
        for q in ex["questions"]:
            it = cleaned.get(f"exam:{i}:{q['n']}")
            if not it:
                continue
            if isinstance(it.get("question"), str) and it["question"].strip():
                q["question"] = it["question"]
            if isinstance(it.get("options"), dict) and set(it["options"]) == set(q["options"]):
                q["options"] = it["options"]
            applied["exam"] += 1
    json.dump(exdata, open(exams_path, "w"), ensure_ascii=False, indent=2)
    # intros
    learn_path = os.path.join(ROOT, "data", "learn.json")
    learn = json.load(open(learn_path))
    for topic, c in learn.items():
        it = cleaned.get(f"intro:{topic}")
        if it and isinstance(it.get("intro"), str) and it["intro"].strip():
            c["intro"] = it["intro"]
            applied["intro"] += 1
    json.dump(learn, open(learn_path, "w"), ensure_ascii=False, indent=2)
    print(f"merge applied: {applied}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "prep"
    (prep if mode == "prep" else merge)()
