#!/usr/bin/env python3
"""Content pipeline: build the Exam P app's data from Finan's manual (PDF).

Stages (run all by default, or pass a stage name):
  curriculum  -> data/curriculum.json   (12 chapters / 52 sections, parsed from the TOC)
  learn       -> data/learn.json         (per-section concept intro prose + counts)
  questions   -> questions/** + index    (ALL questions: worked examples + section practice
                                          problems + sample-exam MCQs, tagged to sections)

Three question types are emitted:
  * worked examples      -> type "free", explanation = the book's full worked Solution
  * section problems     -> type "free", explanation = the short answer from the back-of-book key
  * sample-exam problems -> type "mc",   options A-E + verified answer-key letter

Reads page text from the PDF (pypdf). Run with the pypdf venv; page text is cached.
This script is the source of truth for book-derived content; the generated JSON is committed.
"""
import json, os, re, sys, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.environ.get("PDF_PATH", "/Users/astepchuk/Documents/Pbook.pdf")
PAGES_CACHE = os.environ.get("PBOOK_PAGES_JSON", "/tmp/pbook_pages.json")

CHAPTERS = [
    ("set_theory",        "A Review of Set Theory",                 "∪",  "#993C1D", "#FAECE7"),
    ("counting",          "Counting and Combinatorics",             "#",  "#B25E00", "#FBEEE0"),
    ("prob_defs",         "Probability: Definitions and Properties","P",  "#9A6700", "#FFF4E0"),
    ("conditional",       "Conditional Probability and Independence","∣", "#0F6E56", "#E1F5EE"),
    ("discrete_rv",       "Discrete Random Variables",              "▦",  "#1E7A6F", "#E2F4F1"),
    ("common_discrete",   "Commonly Used Discrete Random Variables","🎲", "#185FA5", "#E6F1FB"),
    ("cdf_survival",      "Cumulative and Survival Distribution Functions","F","#2A5BC8","#E8EDFB"),
    ("calc_prereq",       "Calculus Prerequisite",                  "∫",  "#5B4BC4", "#ECEAFB"),
    ("continuous_rv",     "Continuous Random Variables",            "∿",  "#534AB7", "#EEEDFE"),
    ("joint",             "Joint Distributions",                    "∬",  "#7A3DAE", "#F1E9F9"),
    ("expectation_props", "Properties of Expectation",              "𝔼",  "#A23A8D", "#F9E8F3"),
    ("limit_theorems",    "Limit Theorems",                         "∞",  "#9A2D5A", "#FBE7EF"),
]
CHAP_BY_TITLE = {c[1]: c for c in CHAPTERS}
CHAP_ID = {c[1]: c[0] for c in CHAPTERS}

CHAP_DIFF = {
    "set_theory": 3, "counting": 3, "prob_defs": 4, "conditional": 4, "discrete_rv": 4,
    "common_discrete": 5, "cdf_survival": 5, "calc_prereq": 3, "continuous_rv": 5,
    "joint": 6, "expectation_props": 6, "limit_theorems": 6,
}

LEVELS = [
    {"el": 1.0, "label": "Getting Started",  "icon": "🌱", "desc": "Working through the fundamentals"},
    {"el": 3.0, "label": "Building Up",       "icon": "🧱", "desc": "Earned Level 3 — core ideas landing"},
    {"el": 5.0, "label": "Mid-Difficulty",    "icon": "⚙️", "desc": "Earned Level 5 — handling real exam questions"},
    {"el": 6.0, "label": "Approaching Pass",  "icon": "📈", "desc": "Earned Level 6 — closing in"},
    {"el": 7.0, "label": "Exam Ready",        "icon": "🎯", "desc": "Earned Level 7 — CA's recommended pass threshold"},
    {"el": 8.5, "label": "Comfortably Above", "icon": "🏆", "desc": "Earned Level 8.5 — strong margin over passing"},
]

LIG = {"ﬁ": "fi", "ﬂ": "fl", "‡": "", "’": "'", "“": '"', "”": '"', "−": "-", "···": "…", "·": "*"}
EXAM_STARTS = [458, 478, 496, 516]
EXAM_REGION_END = 534
SECTION_BODY_END = 458        # idx where §52 body ends (Sample Exam 1 begins)
ANSKEY_RANGE = (534, 588)     # idx range of the section answer keys


def slug(s):
    s = s.lower().replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def delig(s):
    for k, v in LIG.items():
        s = s.replace(k, v)
    return s


def para(s):
    return re.sub(r"\s+", " ", delig(s)).strip()


def load_pages():
    if os.path.exists(PAGES_CACHE):
        return json.load(open(PAGES_CACHE))
    from pypdf import PdfReader
    pages = [(p.extract_text() or "") for p in PdfReader(PDF_PATH).pages]
    try:
        json.dump(pages, open(PAGES_CACHE, "w"))
    except Exception:
        pass
    return pages


# --------------------------------------------------------------------------- TOC / curriculum
def parse_toc(pages):
    toc = "\n".join(pages[4:7])
    sections, current_chapter = [], None
    for raw in toc.split("\n"):
        line = raw.replace("ﬁ", "fi").replace("ﬂ", "fl")
        line = re.sub(r"(\s*\.\s*){2,}", " ", line).strip()
        if not line:
            continue
        msec = re.match(r"^(\d{1,2})\s+(.+?)\s*(\d{1,3})$", line)
        if msec and 1 <= int(msec.group(1)) <= 52 and current_chapter:
            title = msec.group(2).strip().rstrip(" .").replace("Contniuous", "Continuous")
            sections.append({"num": int(msec.group(1)), "title": title,
                             "chapter_title": current_chapter, "book_page": int(msec.group(3))})
            continue
        mchap = re.match(r"^([A-Z].+?)\s+(\d{1,3})$", line)
        if mchap and mchap.group(1).strip() in CHAP_BY_TITLE:
            current_chapter = mchap.group(1).strip()
    seen = {s["num"]: s for s in sections}
    return [seen[n] for n in sorted(seen)]


def build_curriculum(pages):
    secs = parse_toc(pages)
    by_chapter = {}
    for s in secs:
        by_chapter.setdefault(s["chapter_title"], []).append(s)
    subjects = [{
        "id": cid, "label": ctitle, "icon": icon, "color": color, "light": light,
        "topics": [f"§{s['num']} {s['title']}" for s in by_chapter.get(ctitle, [])],
    } for cid, ctitle, icon, color, light in CHAPTERS]
    cur = {"exam": "P", "examName": "SOA Exam P — Probability",
           "subtitle": "Built on Finan's “A Probability Course for the Actuaries” · ADAPT + spaced repetition",
           "passLevel": 7.0, "subjects": subjects, "levels": LEVELS}
    json.dump(cur, open(os.path.join(ROOT, "data", "curriculum.json"), "w"), ensure_ascii=False, indent=2)
    print(f"curriculum: {len(subjects)} chapters, {sum(len(s['topics']) for s in subjects)} sections")
    return secs


# --------------------------------------------------------------------------- section bodies
def strip_running(text):
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if re.fullmatch(r"\d{1,3}", s):
            continue
        letters = re.sub(r"[^A-Za-z]", "", s)
        if len(letters) >= 5 and letters.isupper():
            continue
        out.append(ln)
    return "\n".join(out)


def section_starts(pages, secs):
    locs = {}
    for s in secs:
        frag = re.escape(" ".join(delig(s["title"]).split()[:3]))
        pat = re.compile(r"(?m)^\s*" + str(s["num"]) + r"\s+" + frag)
        for i in range(8, len(pages)):
            if pat.search(delig(pages[i])):
                locs[s["num"]] = i
                break
    return locs


def parse_section_body(pages, secs, locs):
    """Return {num: {intro, examples:[{m,problem,solution}], problems:[{m,problem}]}}."""
    ordered = sorted(secs, key=lambda s: s["num"])
    out = {}
    for i, s in enumerate(ordered):
        num = s["num"]
        start = locs[num]
        end = locs[ordered[i + 1]["num"]] if i + 1 < len(ordered) else SECTION_BODY_END
        body = strip_running("\n".join(pages[start:end]))
        parts = re.split(r"\nPractice Problems\b", body, maxsplit=1)
        pre = parts[0]
        practice = parts[1] if len(parts) > 1 else ""

        # examples (with full solutions)
        chunks = re.split(rf"\n?Example\s+{num}\.\d+\s*", pre)
        intro = para(chunks[0])
        intro = re.sub(r"^" + str(num) + r"\s+" + re.escape(delig(s["title"])) + r"\s*", "", intro).strip()
        examples = []
        ex_nums = [int(m.group(1)) for m in re.finditer(rf"Example\s+{num}\.(\d+)", pre)]
        for k, ch in enumerate(chunks[1:]):
            q, sol = (ch.split("Solution.", 1) + [""])[:2] if "Solution." in ch else (ch, "")
            q = para(q)
            if q:
                examples.append({"m": ex_nums[k] if k < len(ex_nums) else k + 1,
                                 "problem": q[:1500], "solution": para(sol)[:2000]})

        # section practice problems
        problems = []
        pmarks = list(re.finditer(rf"Problem\s+{num}\.(\d+)", practice))
        for j, mm in enumerate(pmarks):
            s0 = mm.end()
            e0 = pmarks[j + 1].start() if j + 1 < len(pmarks) else len(practice)
            qtext = para(practice[s0:e0])
            if qtext:
                problems.append({"m": int(mm.group(1)), "problem": qtext[:1500]})
        out[num] = {"intro": intro[:2400], "examples": examples, "problems": problems}
    return out


def parse_section_answers(pages):
    text = delig("\n".join(strip_running(pages[i]) for i in range(*ANSKEY_RANGE)))
    parts = re.split(r"(?m)^\s*Section\s+(\d{1,2})\s*$", text)
    ans = {}
    for j in range(1, len(parts) - 1, 2):
        sec = int(parts[j])
        block = parts[j + 1]
        for m in re.finditer(r"(?ms)^(\d{1,2})\.(\d{1,2})\b[ \t]*(.*?)(?=^\d{1,2}\.\d{1,2}\b|\Z)", block):
            if int(m.group(1)) == sec:
                ans[(sec, int(m.group(2)))] = para(m.group(3))
    return ans


# --------------------------------------------------------------------------- sample-exam MCQs
CLASSIFY = [
    ("hypergeometric", 24), ("negative binomial", 23), ("geometric", 22),
    ("poisson", 20), ("binomial", 18),
    ("central limit", 51), ("law of large numbers", 50), ("chebyshev", 52),
    ("moment generating", 49), ("mgf", 49), ("covariance", 47), ("correlation", 47),
    ("conditional expectation", 48), ("exponential", 36), ("gamma", 37),
    ("uniform", 33), ("normal", 34), ("marginal", 39), ("joint density", 39),
    ("joint distribution", 39), ("jointly", 39), ("survival function", 26),
    ("percentile", 32), ("median", 32), ("mode", 32), ("posterior", 10), ("bayes", 10),
    ("deductible", 36), ("insurance", 30), ("loss", 30), ("density function", 30),
    ("cumulative distribution", 25), ("variance", 31), ("standard deviation", 31),
    ("expected value", 31), ("conditional prob", 9), ("given that", 9),
    ("independent", 11), ("odds", 12), ("permutation", 4), ("committee", 5),
    ("how many ways", 3), ("combination", 5), ("watched", 7), ("union", 7),
    ("intersection", 7), ("at least one", 7),
]
FIGURE_CUES = ["following graph", "graph below", "graph of the", "figure", "diagram",
               "histogram", "shown below", "pictured", "boxplot", "scatter"]


def opt_value(content):
    c = delig(content).strip()
    lines = [ln.strip() for ln in c.split("\n") if ln.strip()]
    if len(lines) == 2 and re.fullmatch(r"[-+]?[\w.]+", lines[0]) and re.fullmatch(r"\d+", lines[1]):
        return f"{lines[0]}/{lines[1]}"
    return re.sub(r"\s+", " ", c)


def parse_mc(body):
    m = re.search(r"\(A\)", body)
    if not m:
        return None
    stem = para(body[:m.start()])
    region = body[m.start():]
    markers = list(re.finditer(r"\(([A-E])\)", region))
    opts = {}
    for i, mm in enumerate(markers):
        e = markers[i + 1].start() if i + 1 < len(markers) else len(region)
        opts[mm.group(1)] = opt_value(region[mm.end():e])
    return (stem, opts) if len(opts) >= 4 else None


def exam_text(start, end):
    buf = []
    for i in range(start, end):
        t = PAGES[i]
        t = re.sub(r"\n?\d{2,3}\s+SAMPLE EXAM [1-4]\n?", "\n", t)
        t = re.sub(r"Sample Exam [1-4]\n", "", t)
        t = re.sub(r"\n\d{2,3}\n", "\n", t)
        buf.append(t)
    return "\n".join(buf)


def parse_key(start, end):
    ans = {}
    for i in range(start, end):
        for m in re.finditer(r"(\d{1,2})\.\s*([A-E])\b", PAGES[i]):
            ans[int(m.group(1))] = m.group(2)
    return ans


def classify(stem):
    low = stem.lower()
    for kw, num in CLASSIFY:
        if kw in low:
            return num
    return 6


# --------------------------------------------------------------------------- emit everything
def build_questions(pages, secs):
    global PAGES
    PAGES = pages
    sec_by_num = {s["num"]: s for s in secs}
    locs = section_starts(pages, secs)
    bodies = parse_section_body(pages, secs, locs)
    answers = parse_section_answers(pages)

    qdir = os.path.join(ROOT, "questions")
    for sub in os.listdir(qdir):
        p = os.path.join(qdir, sub)
        if os.path.isdir(p):
            shutil.rmtree(p)

    index = {"version": 3, "exam": "P", "questions": []}
    file_n = {}
    tally = {"example": 0, "problem": 0, "mc": 0}

    def emit(secnum, qtype, qid, subtopic, question, options, answer, explanation, src, diff_off=0):
        sec = sec_by_num[secnum]
        cid = CHAP_ID[sec["chapter_title"]]
        sslug = slug(sec["title"])
        topic = f"§{sec['num']} {sec['title']}"
        key = (cid, sslug)
        file_n[key] = file_n.get(key, 0) + 1
        rel = f"{cid}/{sslug}/{qid}.json"
        diff = max(1, min(10, CHAP_DIFF[cid] + diff_off))
        rec = {"id": qid, "type": qtype, "subject": sec["chapter_title"], "topic": topic,
               "section": sec["num"], "difficulty": diff, "subtopic": subtopic,
               "question": question, "answer": answer, "explanation": explanation, "source": src}
        if options:
            rec["options"] = options
        out_dir = os.path.join(qdir, cid, sslug)
        os.makedirs(out_dir, exist_ok=True)
        json.dump(rec, open(os.path.join(qdir, rel), "w"), ensure_ascii=False, indent=2)
        index["questions"].append({"id": qid, "type": qtype, "subject": sec["chapter_title"],
                                   "topic": topic, "difficulty": diff, "path": rel})

    # 1) worked examples  (solution = explanation)
    for num, b in bodies.items():
        for ex in b["examples"]:
            emit(num, "free", f"ex-{num}-{ex['m']}",
                 f"Worked Example {num}.{ex['m']}", ex["problem"], None, "",
                 ex["solution"] or "(See the section in Learn.)",
                 f"Finan §{num} — Worked Example {num}.{ex['m']}", diff_off=-1)
            tally["example"] += 1

    # 2) section practice problems  (back-of-book answer = explanation)
    for num, b in bodies.items():
        for pr in b["problems"]:
            a = answers.get((num, pr["m"]), "")
            expl = (f"Answer: {a}" if a else "Answer not listed in the book's key — work it through, then check Finan.")
            emit(num, "free", f"pr-{num}-{pr['m']}",
                 f"Practice Problem {num}.{pr['m']}", pr["problem"], None, a, expl,
                 f"Finan §{num} — Practice Problem {num}.{pr['m']}", diff_off=0)
            tally["problem"] += 1

    # NOTE: the 4 sample exams are intentionally NOT part of this section/ADAPT/SRS pool —
    # they are kept whole as full-length practice tests by build_exams() -> data/exams.json.

    json.dump(index, open(os.path.join(qdir, "index.json"), "w"), ensure_ascii=False, indent=2)
    print(f"questions: {len(index['questions'])} total  ({tally['example']} examples, "
          f"{tally['problem']} section problems) — sample exams kept separate")
    return index


def build_exams(pages):
    """Extract the 4 sample exams whole, in order, as standalone full-length practice tests."""
    global PAGES
    PAGES = pages
    region_bounds = EXAM_STARTS + [EXAM_REGION_END]
    exams = []
    for e in range(4):
        s_start, s_end = region_bounds[e], region_bounds[e + 1]
        key_idx = next((i for i in range(s_start, s_end)
                        if "Answers" in pages[i] and re.search(r"1\.\s*[A-E]", pages[i])), s_end)
        ans = parse_key(key_idx, s_end)
        parts = re.split(r"Problem\s+(\d+)\s*‡?", exam_text(s_start, key_idx))
        questions, skipped = [], 0
        for j in range(1, len(parts) - 1, 2):
            pnum = int(parts[j])
            parsed = parse_mc(parts[j + 1])
            a = ans.get(pnum)
            if not parsed or not a or a not in parsed[1]:
                skipped += 1
                continue
            stem, opts = parsed
            questions.append({"n": pnum, "question": stem, "options": opts, "answer": a})
        questions.sort(key=lambda q: q["n"])
        exams.append({"id": f"sample-exam-{e+1}", "name": f"Sample Exam {e+1}",
                      "count": len(questions), "minutes": 180, "questions": questions})
        print(f"  Sample Exam {e+1}: {len(questions)} questions ({skipped} unparseable/figure-based skipped)")
    out = os.path.join(ROOT, "data", "exams.json")
    json.dump({"exams": exams}, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"exams: {len(exams)} full-length practice tests -> {out}")
    return exams


def build_learn(pages, secs):
    locs = section_starts(pages, secs)
    bodies = parse_section_body(pages, secs, locs)
    learn = {}
    for s in secs:
        b = bodies[s["num"]]
        learn[f"§{s['num']} {s['title']}"] = {
            "intro": b["intro"], "nExamples": len(b["examples"]), "nProblems": len(b["problems"])}
    json.dump(learn, open(os.path.join(ROOT, "data", "learn.json"), "w"), ensure_ascii=False, indent=2)
    print(f"learn: {len(learn)} section intros")
    return learn


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    pages = load_pages()
    secs = parse_toc(pages)
    if stage in ("curriculum", "all"):
        build_curriculum(pages)
    if stage in ("learn", "all"):
        build_learn(pages, secs)
    if stage in ("questions", "practice", "all"):
        build_questions(pages, secs)
    if stage in ("exams", "all"):
        build_exams(pages)
