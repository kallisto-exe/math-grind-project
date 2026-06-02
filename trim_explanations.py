#!/usr/bin/env python3
"""Trim section-prose that the extractor swept into worked-example solutions.

A worked example's `explanation` sometimes runs on into the section's following
theorems/remarks/proofs (because extraction grabbed text up to the next Example).
Cut the explanation at the first marker that clearly starts new section prose,
but only when it removes a substantial tail (so genuine solutions stay intact).

Run with no args for a DRY RUN (stats + samples); pass `apply` to write changes.
"""
import glob, json, re, sys

# Markers that indicate Finan's section prose has resumed after a solution.
CUT = re.compile(
    r"\s+(?:"
    r"Theorem\s+\d+\.\d+"
    r"|Definition\s+\d+\.\d+"
    r"|(?:Corollary|Proposition|Lemma)\s+\d+\.\d+"
    r"|Remark\b"
    r"|The following theorem\b"
    r"|The next theorem\b"
    r"|We illustrate the (?:previous|above)\b"
    r"|[A-Z][a-z]+ Random Variable Histogram\b"
    r")"
)
MIN_KEEP = 100      # don't cut if solution is shorter than this
MIN_REMOVE = 80     # only cut if it removes a meaningful tail


def trim(expl):
    m = CUT.search(expl)
    if not m:
        return expl, 0
    cut = m.start()
    if cut < MIN_KEEP or (len(expl) - cut) < MIN_REMOVE:
        return expl, 0
    return expl[:cut].rstrip(), len(expl) - cut


def main(apply):
    files = [f for f in glob.glob("questions/**/*.json", recursive=True) if not f.endswith("index.json")]
    changed = 0
    removed_total = 0
    samples = []
    for f in files:
        q = json.load(open(f))
        expl = q.get("explanation", "")
        if not expl:
            continue
        new, removed = trim(expl)
        if removed:
            changed += 1
            removed_total += removed
            if len(samples) < 4:
                samples.append((f.split("/")[-1], expl[max(0, len(new) - 40):len(new) + 80]))
            if apply:
                q["explanation"] = new
                json.dump(q, open(f, "w"), ensure_ascii=False, indent=2)
    print(f"{'APPLIED' if apply else 'DRY RUN'}: would trim {changed}/{len(files)} explanations, "
          f"~{removed_total // max(1,changed)} chars avg removed")
    for name, ctx in samples:
        print(f"\n  [{name}] …cut here→ {ctx!r}")


if __name__ == "__main__":
    main(len(sys.argv) > 1 and sys.argv[1] == "apply")
