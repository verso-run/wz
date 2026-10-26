#!/usr/bin/env python3
"""qual-guides helper: the few checks that need no judgement, so the roles can spend their judgement elsewhere.

    python3 tools/qg.py new-project <name>        make projects/<name>/ from projects/_template/
    python3 tools/qg.py sources [--update]        what is in sources/ and what is new or changed since last time
    python3 tools/qg.py quotes <file.md> ...      fetch each link and confirm every quoted line is really on the page
    python3 tools/qg.py lint <guide.md>           flag yes/no, leading, double-barrelled and jargon questions
    python3 tools/qg.py guide-check <guide.md>    the guide has every part, the minutes add up, every question has a probe
    python3 tools/qg.py review-check <review.md> <guide.md>   the review quotes real questions and real methods sources

Plain Python 3.11+, standard library only. Exit code 1 means something needs fixing; the message says what.
A lint flag is a prompt for a person's (or the reviewer's) judgement, not a verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------------------------------------------------
# reading a guide
# --------------------------------------------------------------------------------------------------------------------
QUESTION_RE = re.compile(r"^\s*(?:\*\*)?([QWC]\d+)[.:](?:\*\*)?\s+(.*\S)\s*$")
PROBE_RE = re.compile(r"^\s*[-*]\s*(?:\*\*)?Probe(?:\*\*)?:\s*(.*\S)\s*$", re.I)
HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
MIN_RE = re.compile(r"(\d+)\s*min", re.I)
TOTAL_RE = re.compile(r"^\s*\**Total time:?\**\s*:?\s*(\d+)\s*min", re.I | re.M)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "").replace("*", "").replace("_", " ")).strip().strip('"“”').strip()


def parse_guide(text: str) -> dict:
    """{'sections': [{'level', 'title', 'minutes', 'line'}], 'questions': [{'id','text','section','probes':[...]}]}"""
    sections, questions = [], []
    current = None
    last_q = None
    for n, line in enumerate(text.splitlines(), 1):
        h = HEADING_RE.match(line)
        if h:
            title = h.group(2)
            m = MIN_RE.search(title)
            current = {"level": len(h.group(1)), "title": title, "minutes": int(m.group(1)) if m else None, "line": n}
            sections.append(current)
            last_q = None
            continue
        q = QUESTION_RE.match(line)
        if q:
            last_q = {"id": q.group(1), "text": _clean(q.group(2)), "section": current["title"] if current else "",
                      "probes": [], "line": n}
            questions.append(last_q)
            continue
        p = PROBE_RE.match(line)
        if p and last_q is not None:
            last_q["probes"].append({"id": f"{last_q['id']}{chr(ord('a') + len(last_q['probes']))}",
                                     "text": _clean(p.group(1)), "line": n})
    return {"sections": sections, "questions": questions}


# --------------------------------------------------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------------------------------------------------
AUX = {"do", "does", "did", "is", "are", "was", "were", "have", "has", "had", "can", "could", "will", "would",
       "should", "shall", "may", "might", "must", "am"}
OPEN_POLITE = re.compile(r"^(can|could|would|will) you (please )?(tell|describe|walk|show|explain|share|give|say|think of|"
                         r"remember|talk|take|start|help|paint|bring|name|list)\b", re.I)
EXEMPT_YESNO = re.compile(r"^is there anything\b|^is there something\b|^what\b|^how\b", re.I)
TAG_END = re.compile(r",\s*(right|isn't it|aren't they|aren't you|don't you|wouldn't you|didn't you|wasn't it|"
                     r"doesn't it|correct|yes|no|ok|okay)\s*\?\s*$", re.I)
NEGATIVE_START = re.compile(r"^(don't|doesn't|wouldn't|isn't|aren't|wasn't|weren't|shouldn't|didn't|couldn't|haven't|hasn't)\b", re.I)
PUSHES = re.compile(r"\b(don't you think|wouldn't you agree|would you agree that|do you agree that|surely|obviously|"
                    r"of course|clearly|everyone knows|as you know)\b", re.I)
PRESUPPOSE = re.compile(r"\b(how much (do|would) you (like|love|enjoy|hate)|why do you (like|love|prefer|hate|dislike|enjoy)|"
                        r"when did you (stop|start)|what problems?\b|what struggles?\b|what frustrat\w*)", re.I)
FRAMING = re.compile(r"\b(given that|considering that|seeing as|it'?s only|it is only|only costs?|just [£$€]\d)", re.I)
VALUE_PAIRS = [  # a value word with none of its opposites in the same question suggests the answer
    ({"amazing", "awesome", "great", "wonderful", "fantastic", "excellent", "brilliant", "terrible", "awful", "horrible"}, set()),
    ({"frustrating", "annoying", "irritating", "confusing"}, {"satisfying", "clear", "pleasant", "helpful"}),
    ({"easy", "simple", "effortless"}, {"hard", "difficult", "complicated"}),
    ({"hard", "difficult", "complicated"}, {"easy", "simple", "effortless"}),
    ({"convenient", "helpful", "useful", "valuable", "beneficial"}, {"inconvenient", "unhelpful", "useless", "unhelpful"}),
    ({"inconvenient", "unhelpful", "useless"}, {"convenient", "helpful", "useful"}),
]
JARGON = [
    "stakeholder", "stakeholders", "onboarding", "workflow", "workflows", "pain point", "pain points", "touchpoint",
    "touchpoints", "ux", "user journey", "customer journey", "engagement", "leverage", "utilise", "utilize", "kpi", "kpis",
    "roi", "paradigm", "synergy", "ideate", "value proposition", "persona", "personas", "friction", "affordance",
    "mental model", "intervention", "efficacy", "metrics", "ecosystem", "granular", "solutioning", "capacity building",
    "demographic", "demographics", "cohort", "touch base", "bandwidth", "pivot", "scalable", "buy-in", "deliverable",
    "deliverables", "use case", "use cases", "end user", "end-user", "monetise", "monetize", "retention", "churn",
    "conversion", "funnel", "qualitative", "quantitative", "stakeholder buy-in", "operationalise", "operationalize",
]
CONJ_QUESTION = re.compile(r"\b(and|or|as well as|and also)\s+(what|how|why|when|where|who|which|do|does|did|is|are|was|were|"
                           r"have|has|had|would|could|can|should|will)\b", re.I)
MAX_WORDS = 30

RULE_TAGS = {  # rule -> the `Supports:` tag a methods source must carry for the lint to name it
    "yes-no": "closed", "leading": "leading", "double-barrelled": "double", "jargon": "plain-language",
    "long": "plain-language",
}


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*", text.lower())


_VALUE_WORDS = set().union(*(g | o for g, o in VALUE_PAIRS))


def _loose_conjunction(ws: list[str]) -> bool:
    """An 'and' or 'or' in a longish question, other than a balanced pair like 'easy or hard'."""
    if len(ws) <= 8:
        return False
    for i, w in enumerate(ws):
        if w in ("and", "or") and 0 < i < len(ws) - 1 and not (ws[i - 1] in _VALUE_WORDS and ws[i + 1] in _VALUE_WORDS):
            return True
    return False


def lint_question(text: str, extra_jargon=()) -> list[dict]:
    """The flags for one question. level 'flag' = change it unless you can say why not; 'check' = look at it."""
    t = _clean(text)
    flags: list[dict] = []
    low = t.lower()
    ws = words(t)
    first = ws[0] if ws else ""

    # yes / no
    if first in AUX and not OPEN_POLITE.match(t) and not EXEMPT_YESNO.match(t):
        flags.append({"rule": "yes-no", "level": "flag", "detail": f"starts with “{first}”, so it can be answered yes or no"})

    # leading
    if TAG_END.search(t):
        flags.append({"rule": "leading", "level": "flag", "detail": "ends with a tag (“right?”, “isn't it?”) that asks for agreement"})
    if NEGATIVE_START.match(t):
        flags.append({"rule": "leading", "level": "flag", "detail": "a negative opening (“don't you…”) invites yes"})
    m = PUSHES.search(t)
    if m:
        flags.append({"rule": "leading", "level": "flag", "detail": f"“{m.group(0)}” pushes towards agreeing"})
    m = FRAMING.search(t)
    if m:
        flags.append({"rule": "leading", "level": "flag", "detail": f"“{m.group(0)}” frames the answer before the person gives it"})
    m = PRESUPPOSE.search(t)
    if m:
        flags.append({"rule": "leading", "level": "flag", "detail": f"“{m.group(0)}” assumes something the person has not said"})
    wset = set(ws)
    for group, opposites in VALUE_PAIRS:
        hit = sorted(wset & group)
        if hit and not (wset & opposites):
            flags.append({"rule": "leading", "level": "flag", "detail": f"“{hit[0]}” says how to feel, with no balancing word"})
            break

    # double-barrelled
    if t.count("?") > 1:
        flags.append({"rule": "double-barrelled", "level": "flag", "detail": "more than one question mark"})
    elif CONJ_QUESTION.search(t):
        flags.append({"rule": "double-barrelled", "level": "flag", "detail": "two questions joined by “and/or”"})
    elif _loose_conjunction(ws):
        flags.append({"rule": "double-barrelled", "level": "check", "detail": "has “and/or”: does it ask for two things?"})

    # jargon
    hits = []
    for term in list(JARGON) + [j.lower() for j in extra_jargon]:
        if re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", low):
            hits.append(term)
    if hits:
        flags.append({"rule": "jargon", "level": "flag", "detail": "words your audience may not use: " + ", ".join(sorted(set(hits)))})
    if len(ws) > MAX_WORDS:
        flags.append({"rule": "long", "level": "check", "detail": f"{len(ws)} words; a long question is hard to hold in your head"})
    return flags


def source_map(methods_text: str) -> dict[str, list[str]]:
    """Source ids per Supports: tag, read from the methods base's table: | M1 | title | where | licence | supports |"""
    out: dict[str, list[str]] = {}
    for line in methods_text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.fullmatch(r"M\d+", cells[0]):
            for tag in re.split(r"[,\s]+", cells[4].lower()):
                if tag:
                    out.setdefault(tag, []).append(cells[0])
    return out


def lint_guide(text: str, extra_jargon=(), sources: dict[str, list[str]] | None = None) -> list[dict]:
    parsed = parse_guide(text)
    results = []
    for q in parsed["questions"]:
        items = [("question", q["id"], q["text"])] + [("probe", p["id"], p["text"]) for p in q["probes"]]
        for kind, ident, t in items:
            flags = lint_question(t, extra_jargon)
            if kind == "probe":  # probes are allowed to be short and plain; only the real problems count
                flags = [f for f in flags if f["rule"] in ("leading", "double-barrelled", "jargon")]
            if sources is not None:
                for f in flags:
                    f["sources"] = sources.get(RULE_TAGS[f["rule"]], [])
            results.append({"id": ident, "kind": kind, "text": t, "flags": flags})
    return results


# --------------------------------------------------------------------------------------------------------------------
# guide structure
# --------------------------------------------------------------------------------------------------------------------
PARTS = [("what we want to learn", r"\b(learn|goals?)\b"), ("who to talk to", r"\bwho to talk"),
         ("consent and recording script", r"\bconsent"), ("warm-up", r"\bwarm"), ("core questions", r"\bcore\b"),
         ("closing", r"\bclos"), ("how to run this interview (card)", r"\bhow to run")]


def guide_problems(text: str) -> list[str]:
    g = parse_guide(text)
    probs: list[str] = []
    top = [s for s in g["sections"] if s["level"] == 2]
    found = {}
    for name, rx in PARTS:
        match = next((s for s in top if re.search(rx, s["title"], re.I)), None)
        if match is None:
            probs.append(f"missing part: {name}")
        found[name] = match
    # minutes
    parts = ["consent and recording script", "warm-up", "core questions", "closing"]
    total = 0
    for name in parts:
        s = found.get(name)
        if s is None:
            continue
        mins = s["minutes"]
        if name == "core questions":
            subs = _subsections(g["sections"], s)
            sub_mins = [x["minutes"] for x in subs]
            if subs and all(m is not None for m in sub_mins):
                mins = sum(sub_mins) if mins is None else mins
                # Topics for different groups of people may be skipped, so the heading may be less than the sum of the
                # topics (but never more: that time could not be filled).
                if s["minutes"] is not None and s["minutes"] > sum(sub_mins):
                    probs.append(f"core questions say {s['minutes']} min but their topics add up to only {sum(sub_mins)} min")
        if mins is None:
            probs.append(f"no minutes on “{s['title']}” (write it like “— 5 min”)")
        else:
            total += mins
    m = TOTAL_RE.search(text)
    if not m:
        probs.append("no “Total time: N minutes” line near the top")
    elif total and int(m.group(1)) != total:
        probs.append(f"Total time says {m.group(1)} min but the parts add up to {total} min")
    # questions
    core = [q for q in g["questions"] if q["id"].startswith("Q")]
    if not core:
        probs.append("no core questions (lines that start “Q1.”)")
    if len(core) > 10:
        probs.append(f"{len(core)} core questions is too many to ask in one sitting (10 at most)")
    for q in core:
        if not q["probes"]:
            probs.append(f"{q['id']} has no follow-up probe (a line “- Probe: …”)")
    ids = [q["id"] for q in g["questions"]]
    if len(ids) != len(set(ids)):
        probs.append("a question number is used twice")
    # consent words
    cs = found.get("consent and recording script")
    if cs:
        body = re.sub(r"[\s>]+", " ", _body(text, g["sections"], cs)).lower()  # a script wrapped over lines or quote marks
        for need, rx in (("recording", r"record"), ("they can stop or skip", r"\b(stop|skip|pause)\b"),
                         ("confidentiality", r"confiden|private|anonym|name"), ("no wrong answers", r"no (right or )?wrong")):
            if not re.search(rx, body):
                probs.append(f"the consent script never mentions {need}")
    card = found.get("how to run this interview (card)")
    if card:
        n = len([ln for ln in _body(text, g["sections"], card).splitlines() if ln.strip()])
        if n > 30:
            probs.append(f"the how-to-run card is {n} lines; a card fits on one page (30 lines at most)")
    return probs


def _subsections(sections, parent):
    out = []
    i = sections.index(parent)
    for s in sections[i + 1:]:
        if s["level"] <= parent["level"]:
            break
        out.append(s)
    return out


def _body(text: str, sections, sec) -> str:
    lines = text.splitlines()
    i = sections.index(sec)
    end = next((s["line"] for s in sections[i + 1:] if s["level"] <= sec["level"]), len(lines) + 1)
    return "\n".join(lines[sec["line"]:end - 1])


# --------------------------------------------------------------------------------------------------------------------
# review
# --------------------------------------------------------------------------------------------------------------------
FLAG_WORDS = ("leading", "double", "jargon", "yes", "closed", "long", "other")


def _norm(s: str) -> str:
    s = html.unescape(s).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", "", s).casefold()


def _table_rows(text: str) -> list[dict]:
    rows, head = [], None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            head = None  # a line that is not a table row ends the table
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if head is None:
            head = [c.lower() for c in cells]
            continue
        rows.append(dict(zip(head, cells)))
    return rows


def review_problems(review: str, guide: str, methods: str | None = None) -> list[str]:
    probs: list[str] = []
    if not re.search(r"^\s*\**Verdict:?\**\s*:?\s*(PASS|CHANGES NEEDED)\b", review, re.I | re.M):
        probs.append("no “Verdict: PASS” or “Verdict: CHANGES NEEDED” line")
    g = _norm(guide)
    known = set(source_ids(methods)) if methods is not None else None
    rows = [r for r in _table_rows(review) if any(k in r for k in ("question", "where"))]
    passed = re.search(r"^\s*\**Verdict:?\**\s*:?\s*PASS\b", review, re.I | re.M)
    if not rows and not passed:  # a PASS may have no findings; anything else needs its table
        probs.append("no findings table (columns: Where | Question | Flag | Why | Method source | Suggested rewrite)")
    for r in rows:
        where = r.get("where", "?")
        quote = r.get("question", "").strip().strip('"“”')
        if not quote or _norm(quote) not in g:
            probs.append(f"{where}: the quoted question is not in the guide")
        flag = r.get("flag", "").lower()
        if not any(w in flag for w in FLAG_WORDS):
            probs.append(f"{where}: flag “{r.get('flag', '')}” is not one of leading, double-barrelled, jargon, yes/no, long")
        ids = re.findall(r"\bM\d+\b", r.get("method source", ""))
        if not ids:
            probs.append(f"{where}: no methods source named")
        elif known is not None:
            for i in ids:
                if i not in known:
                    probs.append(f"{where}: {i} is not in the methods base")
    parsed = parse_guide(guide)
    flagged = [x["id"] for x in lint_guide(guide) if any(f["level"] == "flag" for f in x["flags"])]
    for ident in flagged:
        if not re.search(r"(?<![A-Za-z0-9])" + re.escape(ident) + r"(?![A-Za-z0-9])", review):
            probs.append(f"lint flags {ident} in the guide but the review never mentions it")
    covered = {q["id"] for q in parsed["questions"] if re.search(r"(?<![A-Za-z0-9])" + re.escape(q["id"]) + r"(?![A-Za-z0-9])", review)}
    if parsed["questions"] and len(covered) < len(parsed["questions"]) // 2:
        probs.append("the review mentions fewer than half of the guide's questions; say that each one was read")
    return probs


def source_ids(methods_text: str) -> list[str]:
    ids = []
    for line in methods_text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"M\d+", cells[0]):
            ids.append(cells[0])
    return ids


# --------------------------------------------------------------------------------------------------------------------
# sources and quotes
# --------------------------------------------------------------------------------------------------------------------
URL_RE = re.compile(r"https?://[^\s<>)\]\"']+[^\s<>)\]\"'.,;:]")
QUOTE_RE = re.compile(r"^\s*[-*>]?\s*(?:Quoted line|Quote)\s*:\s*[\"“](.+)[\"”]\s*$", re.I)
MAX_QUOTE_WORDS = 40
TEXT_SUFFIX = {".md", ".txt", ".url", ".webloc", ".html", ".htm", ".csv"}


def scan_sources(src: Path) -> list[dict]:
    items = []
    for p in sorted(src.rglob("*")) if src.is_dir() else []:
        if not p.is_file() or p.name.startswith(".") or (p.parent == src and p.name.lower() == "readme.md"):
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        kind = "pdf" if p.suffix.lower() == ".pdf" else "text" if p.suffix.lower() in TEXT_SUFFIX else "other"
        urls = sorted(set(URL_RE.findall(p.read_text(errors="replace")))) if kind == "text" else []
        items.append({"file": str(p.relative_to(src)), "kind": kind, "sha": digest, "size": p.stat().st_size, "urls": urls})
    return items


def sources_report(root: Path, update: bool = False) -> dict:
    src = root / "sources"
    index_path = root / "methods-base" / "sources-index.json"
    old = json.loads(index_path.read_text()) if index_path.is_file() else {}
    items = scan_sources(src)
    for it in items:
        was = old.get(it["file"])
        it["status"] = "new" if was is None else "unchanged" if was.get("sha") == it["sha"] else "changed"
    gone = sorted(set(old) - {i["file"] for i in items})
    if update:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps({i["file"]: {"sha": i["sha"], "urls": i["urls"]} for i in items}, indent=2) + "\n")
    return {"items": items, "removed": gone}


def fetch_text(url: str, timeout: int = 40) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (qual-guides quote check)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (http/https only, checked by the caller)
        raw = r.read()
    body = raw.decode("utf-8", errors="replace")
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
    return html.unescape(re.sub(r"<[^>]+>", "", body))


def extract_quotes(text: str) -> list[tuple[int, str, str]]:
    """(line, url, quote) for each Quote: line, tied to the last link seen above it."""
    out, last = [], ""
    for n, line in enumerate(text.splitlines(), 1):
        q = QUOTE_RE.match(line)
        if q:
            out.append((n, last, q.group(1).strip()))
            continue
        urls = URL_RE.findall(line)
        if urls:
            last = urls[0]
    return out


def quote_problems(path: Path, fetch=fetch_text) -> list[str]:
    probs, cache = [], {}
    for n, url, quote in extract_quotes(path.read_text()):
        where = f"{path.name}:{n}"
        if not url.startswith(("http://", "https://")):
            probs.append(f"{where}: quote has no link above it")
            continue
        if len(quote.split()) > MAX_QUOTE_WORDS:
            probs.append(f"{where}: quote is {len(quote.split())} words; keep it under {MAX_QUOTE_WORDS} (short quotes only)")
        if url not in cache:
            try:
                cache[url] = _norm(fetch(url))
            except Exception as e:  # network, DNS, HTTP error: a quote we could not check is not a checked quote
                cache[url] = e
        page = cache[url]
        if isinstance(page, Exception):
            probs.append(f"{where}: could not fetch {url} ({page.__class__.__name__}: {page})")
        elif _norm(quote.replace("…", "").replace("...", "")) not in page:
            probs.append(f"{where}: this line is not on {url}: “{quote[:70]}”")
    return probs


# --------------------------------------------------------------------------------------------------------------------
# projects
# --------------------------------------------------------------------------------------------------------------------
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def new_project(root: Path, name: str) -> Path:
    if not NAME_RE.match(name):
        raise ValueError("a project name is lower-case letters, numbers and dashes (2 to 41 characters), like “corner-shop”")
    tpl, dest = root / "projects" / "_template", root / "projects" / name
    if dest.exists():
        raise ValueError(f"{dest} already exists")
    if not tpl.is_dir():
        raise ValueError(f"no template at {tpl}")
    shutil.copytree(tpl, dest, ignore=shutil.ignore_patterns("*-layout.md"))  # the layouts stay in the template
    return dest


# --------------------------------------------------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------------------------------------------------
def _read(p: str) -> str:
    return Path(p).read_text()


def _jargon_for(guide_path: Path) -> list[str]:
    j = guide_path.parent / "jargon.txt"
    return [x.strip() for x in j.read_text().splitlines() if x.strip() and not x.startswith("#")] if j.is_file() else []


def _methods_for(root: Path) -> str | None:
    m = root / "methods-base" / "METHODS-BASE.md"
    return m.read_text() if m.is_file() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qg.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT), help="the qual-guides folder (default: this one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new-project"); s.add_argument("name")
    s = sub.add_parser("sources"); s.add_argument("--update", action="store_true")
    s = sub.add_parser("quotes"); s.add_argument("files", nargs="+")
    s = sub.add_parser("lint"); s.add_argument("guide"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("guide-check"); s.add_argument("guide")
    s = sub.add_parser("review-check"); s.add_argument("review"); s.add_argument("guide")
    a = ap.parse_args(argv)
    root = Path(a.root)

    if a.cmd == "new-project":
        try:
            dest = new_project(root, a.name)
        except ValueError as e:
            print(f"qg: {e}")
            return 1
        print(f"made {dest}: fill in brief.md and audience.md, put any other documents in {dest / 'docs'}")
        return 0

    if a.cmd == "sources":
        rep = sources_report(root, update=a.update)
        if not rep["items"]:
            print("sources/ is empty: drop PDFs, notes or a list of links in there")
        for it in rep["items"]:
            extra = f"  links: {len(it['urls'])}" if it["urls"] else ""
            print(f"{it['status']:<10} {it['kind']:<5} {it['file']}{extra}")
            for u in it["urls"]:
                print(f"             {u}")
        for g in rep["removed"]:
            print(f"removed    {g}")
        if a.update:
            print("index updated")
        return 0

    if a.cmd == "quotes":
        probs = []
        for f in a.files:
            probs += quote_problems(Path(f))
        print("\n".join(probs) if probs else "every quoted line was found on its page")
        return 1 if probs else 0

    if a.cmd == "lint":
        gp = Path(a.guide)
        methods = _methods_for(root)
        res = lint_guide(gp.read_text(), _jargon_for(gp), source_map(methods) if methods else None)
        if a.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            n = 0
            for r in res:
                for f in r["flags"]:
                    n += f["level"] == "flag"
                    src = f" [{', '.join(f['sources'])}]" if f.get("sources") else ""
                    print(f"{r['id']:<5} {f['level']:<5} {f['rule']:<17} {f['detail']}{src}\n      “{r['text']}”")
            print(f"\n{len(res)} questions and probes read, {n} flags")
        return 1 if any(f["level"] == "flag" for r in res for f in r["flags"]) else 0

    if a.cmd == "guide-check":
        probs = guide_problems(_read(a.guide))
        print("\n".join(probs) if probs else "the guide has every part, the minutes add up, every question has a probe")
        return 1 if probs else 0

    if a.cmd == "review-check":
        probs = review_problems(_read(a.review), _read(a.guide), _methods_for(root))
        print("\n".join(probs) if probs else "the review quotes real questions and names real methods sources")
        return 1 if probs else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
