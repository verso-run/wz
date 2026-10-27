"""The qual-guides example: its checker (tools/qg.py), its setup answers, and the shipped sample.

Nothing here needs Claude or a network: the quote check is run against a local web server. One test, which checks the
shipped research note's quotes against the real pages, runs only when WZ_TEST_NETWORK=1 is set.
"""
import functools
import http.server
import importlib.util
import json
import os
import re
import shlex
import threading
from pathlib import Path

import pytest

from wz import config, guard, setup_mode
from conftest import payload

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples" / "qual-guides"
SAMPLE = EX / "projects" / "larkspur-tool-library"
CHAIN = EX / "projects" / "car-scent-study"
SAMPLES = (SAMPLE, CHAIN)


def _load():
    spec = importlib.util.spec_from_file_location("qg", EX / "tools" / "qg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qg = _load()

GOOD_GUIDE = """# Discussion guide: Corner shop

Total time: 30 minutes
For: the owner

## 1. What we want to learn
1. How neighbours do their weekly shop.

## 2. Who to talk to
Six neighbours.

## 3. Consent and recording script (read aloud) — 3 min
> "I would like to record so I can listen again. You can skip any question or stop at any time. There are no right or
> wrong answers. Your name will not be used. Is it all right if I record?"

## 4. Warm-up — 5 min
W1. Tell me about your street.

## 5. Core questions — 18 min total
### 5.1 Shopping — 10 min
Q1. Tell me about the last time you did a big shop.
- Probe: What happened next?

### 5.2 Corner shop — 8 min
Q2. What have you heard about the shop on the corner?
- Probe: Tell me more about that.

## 6. Closing — 4 min
C1. Is there anything we have not talked about that you think I should know?

## 7. How to run this interview (card)
- Wait for a yes before recording.
"""


# ---- the guide parser and the lint ---------------------------------------------------------------------------------
def test_parse_guide_finds_questions_probes_and_minutes():
    g = qg.parse_guide(GOOD_GUIDE)
    assert [q["id"] for q in g["questions"]] == ["W1", "Q1", "Q2", "C1"]
    q1 = g["questions"][1]
    assert q1["text"].startswith("Tell me about the last time")
    assert [p["id"] for p in q1["probes"]] == ["Q1a"]
    assert {s["title"]: s["minutes"] for s in g["sections"]}["5.1 Shopping — 10 min"] == 10


def rules(text, **kw):
    return {f["rule"] for f in qg.lint_question(text, **kw) if f["level"] == "flag"}


@pytest.mark.parametrize("text", [
    "Tell me about the last time you needed a tool you did not own.",
    "What happened next?",
    "How easy or hard was it to find what you wanted when you first walked in?",
    "Could you tell me what happened next?",
    "Can you give me an example?",
    "Is there anything we have not talked about that you think I should know?",
    "Walk me through a typical week for you.",
])
def test_clean_questions_have_no_flags(text):
    assert qg.lint_question(text) == []


@pytest.mark.parametrize("text,rule", [
    ("Do you find our opening hours inconvenient?", "yes-no"),
    ("Would you borrow more if we had more tools?", "yes-no"),
    ("Do you find our opening hours inconvenient?", "leading"),
    ("The new menu is easier to use, isn't it?", "leading"),
    ("Don't you think the fee is fair?", "leading"),
    ("Why don't you join, given that it's only £20 a year?", "leading"),
    ("How much would you love a weekday evening session?", "leading"),
    ("How easy was it to find what you wanted?", "leading"),
    ("What did you do, and how did that go?", "double-barrelled"),
    ("How often do you visit? How long do you stay?", "double-barrelled"),
    ("How do your stakeholders feel about the workflow?", "jargon"),
    ("How was the onboarding for new members?", "jargon"),
])
def test_flagged_questions(text, rule):
    assert rule in rules(text)


def test_project_jargon_list_and_long_questions():
    assert "jargon" not in rules("What do you think of the shelf-life labels?")
    assert "jargon" in rules("What do you think of the shelf-life labels?", extra_jargon=["shelf-life"])
    long_q = "Tell me " + " ".join(["more"] * 35)
    assert any(f["rule"] == "long" and f["level"] == "check" for f in qg.lint_question(long_q))


def test_probes_are_not_held_to_the_yes_no_rule():
    guide = GOOD_GUIDE.replace("- Probe: What happened next?", "- Probe: Did that work?")
    flagged = {r["id"]: [f["rule"] for f in r["flags"]] for r in qg.lint_guide(guide)}
    assert flagged["Q1a"] == []
    guide = GOOD_GUIDE.replace("Tell me about the last time you did a big shop.", "Do you shop weekly?")
    assert "yes-no" in {f["rule"] for r in qg.lint_guide(guide) if r["id"] == "Q1" for f in r["flags"]}


def test_lint_names_the_methods_source_for_each_rule():
    methods = (EX / "methods-base" / "METHODS-BASE.md").read_text()
    smap = qg.source_map(methods)
    assert smap["leading"] and smap["double"] and smap["closed"] and smap["plain-language"]
    guide = GOOD_GUIDE.replace("Tell me about the last time you did a big shop.", "Do you shop weekly, and how do you get there?")
    res = qg.lint_guide(guide, sources=smap)
    q1 = next(r for r in res if r["id"] == "Q1")
    by_rule = {f["rule"]: f["sources"] for f in q1["flags"]}
    assert by_rule["yes-no"] == smap["closed"]
    assert by_rule["double-barrelled"] == smap["double"]


def test_lint_cli_exit_code(tmp_path, capsys):
    g = tmp_path / "guide.md"
    g.write_text(GOOD_GUIDE)
    assert qg.main(["--root", str(EX), "lint", str(g)]) == 0
    g.write_text(GOOD_GUIDE.replace("Tell me about your street.", "Do you like your street?"))
    assert qg.main(["--root", str(EX), "lint", str(g)]) == 1
    assert "yes-no" in capsys.readouterr().out


# ---- guide structure -----------------------------------------------------------------------------------------------
def test_good_guide_passes():
    assert qg.guide_problems(GOOD_GUIDE) == []


@pytest.mark.parametrize("edit,expect", [
    (lambda g: g.replace("## 6. Closing — 4 min", "## 6. Finishing off — 4 min"), "missing part: closing"),
    (lambda g: g.replace("Total time: 30 minutes", "Total time: 45 minutes"), "add up to 30"),
    (lambda g: g.replace("Total time: 30 minutes\n", ""), "no “Total time"),
    (lambda g: g.replace("## 4. Warm-up — 5 min", "## 4. Warm-up"), "no minutes on"),
    (lambda g: g.replace("- Probe: What happened next?\n", ""), "Q1 has no follow-up probe"),
    (lambda g: g.replace("## 5. Core questions — 18 min total", "## 5. Core questions — 25 min total"), "only 18 min"),
    (lambda g: g.replace("You can skip any question or stop at any time. ", ""), "never mentions they can stop or skip"),
    (lambda g: g.replace("There are no right or\n> wrong answers. ", ""), "no wrong answers"),
    (lambda g: g.replace("record so I", "tape so I").replace("if I record", "if I tape"), "never mentions recording"),
    (lambda g: g + "".join(f"- line {i}\n" for i in range(40)), "card is"),
    (lambda g: g.replace("Q2.", "Q1."), "used twice"),
])
def test_guide_problems(edit, expect):
    probs = qg.guide_problems(edit(GOOD_GUIDE))
    assert any(expect in p for p in probs), probs


def test_core_heading_may_be_less_than_its_topics_when_groups_branch():
    guide = GOOD_GUIDE.replace("## 5. Core questions — 18 min total", "## 5. Core questions — 10 min total")
    guide = guide.replace("Total time: 30 minutes", "Total time: 22 minutes")
    assert qg.guide_problems(guide) == []


def test_more_than_ten_core_questions_is_too_many():
    extra = "".join(f"Q{i}. Tell me about thing {i}.\n- Probe: Tell me more.\n" for i in range(3, 13))
    probs = qg.guide_problems(GOOD_GUIDE.replace("## 6. Closing", extra + "\n## 6. Closing"))
    assert any("too many" in p for p in probs)


# ---- reviews -------------------------------------------------------------------------------------------------------
METHODS = "| id | title | link | licence | supports |\n|---|---|---|---|---|\n| M1 | A | http://x | CC | leading, probes |\n| M5 | B | http://y | CC | closed |\n"
REVIEW = """# Review: Corner shop

Verdict: CHANGES NEEDED

## Findings
| Where | Question | Flag | Why | Method source | Suggested rewrite |
|---|---|---|---|---|---|
| Q2 | "What have you heard about the shop on the corner?" | leading | because | M1 | "x" |

Read: W1, Q1, C1, Q2.
"""


def test_review_check_accepts_a_good_review():
    assert qg.review_problems(REVIEW, GOOD_GUIDE, METHODS) == []


@pytest.mark.parametrize("edit,expect", [
    (lambda r: r.replace("Verdict: CHANGES NEEDED", ""), "no “Verdict"),
    (lambda r: r.replace("What have you heard about the shop on the corner?", "Something that is not in the guide"), "not in the guide"),
    (lambda r: r.replace("| M1 |", "| M9 |"), "M9 is not in the methods base"),
    (lambda r: r.replace("| M1 |", "| not covered |"), "no methods source named"),
    (lambda r: r.replace("| leading |", "| vibes |"), "is not one of"),
    (lambda r: r.split("## Findings")[0], "no findings table"),
])
def test_review_problems(edit, expect):
    probs = qg.review_problems(edit(REVIEW), GOOD_GUIDE, METHODS)
    assert any(expect in p for p in probs), probs


def test_the_flag_message_lists_every_flag_the_checker_accepts():
    probs = qg.review_problems(REVIEW.replace("| leading |", "| vibes |"), GOOD_GUIDE, METHODS)
    msg = next(p for p in probs if "is not one of" in p)
    assert all(w in msg for w in qg.FLAG_WORDS), msg
    assert "other" in msg


def test_review_must_mention_every_question_the_lint_flagged():
    guide = GOOD_GUIDE.replace("Tell me about the last time you did a big shop.", "Do you shop weekly?")
    unread = REVIEW.replace("Read: W1, Q1, C1, Q2.", "Read: W1, C1, Q2.")
    probs = qg.review_problems(unread, guide, METHODS)
    assert any("lint flags Q1" in p for p in probs)
    ok = REVIEW.replace("Read: W1, Q1, C1, Q2.", "Q1 (\"Do you shop weekly?\") is closed. Read: W1, C1, Q2.")
    assert not any("lint flags Q1" in p for p in qg.review_problems(ok, guide, METHODS))


def test_a_pass_may_have_no_findings():
    review = "# Review\n\nVerdict: PASS\n\nI read W1, Q1, Q2 and C1; all fine.\n"
    assert qg.review_problems(review, GOOD_GUIDE, METHODS) == []


# ---- sources, projects ---------------------------------------------------------------------------------------------
def test_sources_new_changed_unchanged_removed(tmp_path):
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "README.md").write_text("instructions: ignored")
    (tmp_path / "sources" / "links.md").write_text("see https://example.org/a and (https://example.org/b).\n")
    (tmp_path / "sources" / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    rep = qg.sources_report(tmp_path)
    assert {i["file"]: i["status"] for i in rep["items"]} == {"links.md": "new", "paper.pdf": "new"}
    assert rep["items"][0]["urls"] == ["https://example.org/a", "https://example.org/b"]
    qg.sources_report(tmp_path, update=True)
    assert {i["status"] for i in qg.sources_report(tmp_path)["items"]} == {"unchanged"}
    (tmp_path / "sources" / "links.md").write_text("changed https://example.org/c\n")
    (tmp_path / "sources" / "paper.pdf").unlink()
    (tmp_path / "sources" / "notes.txt").write_text("my notes")
    rep = qg.sources_report(tmp_path)
    assert {i["file"]: i["status"] for i in rep["items"]} == {"links.md": "changed", "notes.txt": "new"}
    assert rep["removed"] == ["paper.pdf"]


def test_new_project_copies_the_template_but_not_the_layouts(tmp_path):
    shutil_copy = __import__("shutil").copytree
    shutil_copy(EX / "projects" / "_template", tmp_path / "projects" / "_template")
    dest = qg.new_project(tmp_path, "corner-shop")
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["audience.md", "brief.md", "docs"]
    with pytest.raises(ValueError, match="already exists"):
        qg.new_project(tmp_path, "corner-shop")
    for bad in ("../x", "Corner Shop", "a", ""):
        with pytest.raises(ValueError):
            qg.new_project(tmp_path, bad)


# ---- the checker's write modes belong to one role each, and its folder is its own ----------------------------------------
@pytest.fixture()
def qg_ws(tmp_path, monkeypatch):
    """A scratch qual-guides folder that the checker takes to be its own."""
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "links.md").write_text("see https://example.org/a\n")
    __import__("shutil").copytree(EX / "projects" / "_template", tmp_path / "projects" / "_template")
    monkeypatch.setattr(qg, "ROOT", tmp_path)
    monkeypatch.delenv("WZ_ROLE", raising=False)
    return tmp_path


INDEX = Path("methods-base") / "sources-index.json"


@pytest.mark.parametrize("role", [None, "reviewer", "mission-ctl", "guide-writer", "designer", "Librarian"])
def test_sources_update_refuses_every_role_but_the_librarian(qg_ws, monkeypatch, capsys, role):
    if role:
        monkeypatch.setenv("WZ_ROLE", role)
    assert qg.main(["sources", "--update"]) == 1
    assert "librarian" in capsys.readouterr().out
    assert not (qg_ws / INDEX).exists()
    assert qg.main(["sources"]) == 0                                    # reading is open to everyone


def test_sources_update_runs_for_the_librarian_and_reading_never_writes(qg_ws, monkeypatch):
    monkeypatch.setenv("WZ_ROLE", "librarian")
    assert qg.main(["sources"]) == 0 and not (qg_ws / INDEX).exists()
    assert qg.main(["sources", "--update"]) == 0 and (qg_ws / INDEX).is_file()


def test_new_project_is_the_leads_alone(qg_ws, monkeypatch, capsys):
    for role in (None, "librarian", "reviewer"):
        if role:
            monkeypatch.setenv("WZ_ROLE", role)
        assert qg.main(["new-project", "corner-shop"]) == 1
        assert "mission-ctl" in capsys.readouterr().out
        assert not (qg_ws / "projects" / "corner-shop").exists()
    monkeypatch.setenv("WZ_ROLE", "mission-ctl")
    assert qg.main(["new-project", "corner-shop"]) == 0 and (qg_ws / "projects" / "corner-shop" / "brief.md").is_file()


def test_root_outside_the_workspace_is_refused_whatever_the_role(qg_ws, tmp_path_factory, monkeypatch, capsys):
    other = tmp_path_factory.mktemp("elsewhere")
    (other / "sources").mkdir()
    (other / "sources" / "a.md").write_text("x")
    for role, argv in (("librarian", ["sources", "--update"]), ("librarian", ["sources"]), ("mission-ctl", ["new-project", "zz"])):
        monkeypatch.setenv("WZ_ROLE", role)
        assert qg.main(["--root", str(other), *argv]) == 1
        assert "outside this workspace" in capsys.readouterr().out
    assert not (other / INDEX).exists() and not (other / "projects").exists()
    # a path that climbs back out, and a link that points out, are the same folder
    monkeypatch.setenv("WZ_ROLE", "librarian")
    assert qg.main(["--root", str(qg_ws / ".." / other.name), "sources", "--update"]) == 1
    (qg_ws / "link").symlink_to(other)
    assert qg.main(["--root", str(qg_ws / "link"), "sources", "--update"]) == 1
    assert not (other / INDEX).exists()
    # inside the workspace is fine
    (qg_ws / "sub").mkdir()
    assert qg.main(["--root", str(qg_ws / "sub"), "sources"]) == 0
    assert qg.main(["--root", str(qg_ws), "sources", "--update"]) == 0


def test_the_librarians_rule_and_the_readme_name_the_write_modes():
    ans = json.loads((EX / "answers.json").read_text())
    assert "python3 tools/qg.py sources --update" in " ".join(ans["roles"]["librarian"]["rules"])
    assert "python3 tools/qg.py new-project" in " ".join(ans["roles"]["mission-ctl"]["rules"])
    assert qg.WRITERS == {"new-project": "mission-ctl", "sources --update": "librarian"}
    readme = (EX / "README.md").read_text()
    assert "only the librarian may run it" in readme and "only the coordinator, `mission-ctl`, may run it" in readme


# ---- quotes, against a local server --------------------------------------------------------------------------------
@pytest.fixture()
def page_server(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "page.html").write_text(
        "<html><body><h1>Interviews</h1><p>Avoid <b>leading</b> questions. A good interviewer will "
        "focus on what the participant wants to say.</p><p>Keep it within an hour &amp; take a break.</p></body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_quotes_are_found_on_the_page(tmp_path, page_server):
    f = tmp_path / "links.md"
    f.write_text(f"1. {page_server}/page.html — a page\n"
                 '   - Quote: "Avoid leading questions. A good interviewer will focus on what the participant wants to say."\n'
                 '   - Quote: "Keep it within an hour & take a break."\n')
    assert qg.quote_problems(f) == []


def test_a_missing_quote_a_missing_page_and_a_long_quote_are_reported(tmp_path, page_server):
    f = tmp_path / "links.md"
    long_quote = " ".join(["word"] * 45)
    f.write_text(f"{page_server}/page.html\n"
                 '- Quote: "Always ask leading questions."\n'
                 f'- Quote: "{long_quote}"\n'
                 f"{page_server}/nothing-here.html\n"
                 '- Quote: "Avoid leading questions."\n')
    probs = qg.quote_problems(f)
    assert any("is not on" in p and "Always ask" in p for p in probs)
    assert any("45 words" in p for p in probs)
    assert any("could not fetch" in p for p in probs)


def test_a_quote_may_end_with_a_full_stop_the_page_continues_past(tmp_path):
    f = tmp_path / "links.md"
    f.write_text('https://example.org/p\n- Quote: "Keep it short."\n- Quote: "Ask about last week."\n')
    page = "<p>Keep it short; ask about last week, then stop.</p>"
    assert qg.quote_problems(f, fetch=lambda url: page) == []
    f.write_text('https://example.org/p\n- Quote: "Keep it long."\n')  # a wrong word still fails
    assert any("is not on" in p for p in qg.quote_problems(f, fetch=lambda url: page))


def test_a_page_that_fails_once_is_tried_again_before_a_quote_is_called_missing(tmp_path):
    f = tmp_path / "links.md"
    f.write_text('https://example.org/p\n- Quote: "Keep it short."\n')
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("reset")
        return "<p>Keep it short.</p>"

    assert qg.quote_problems(f, fetch=flaky) == []
    assert len(calls) == 2

    pages = iter(["<p>An error page.</p>", "<p>Keep it short.</p>"])  # a page that loaded wrongly, then right
    assert qg.quote_problems(f, fetch=lambda url: next(pages)) == []

    def dead(url):
        raise OSError("down")

    assert any("could not fetch" in p for p in qg.quote_problems(f, fetch=dead))


def test_a_quote_with_no_link_above_it_is_reported(tmp_path):
    f = tmp_path / "x.md"
    f.write_text('- Quote: "Something nobody can check."\n')
    assert any("no link above" in p for p in qg.quote_problems(f))


def test_pdf_quotes_are_marked_and_not_machine_checked(tmp_path):
    f = tmp_path / "x.md"
    f.write_text('- Quote (from the PDF, page 3): "Something from a file."\n')
    assert qg.extract_quotes(f.read_text()) == []


# ---- the shipped material ------------------------------------------------------------------------------------------
def test_shipped_sources_are_short_quotes_with_links_and_licences():
    for name in ("sources/links.md", "methods-base/METHODS-BASE.md"):
        text = (EX / name).read_text()
        quotes = qg.extract_quotes(text)
        assert quotes, name
        for line, url, quote in quotes:
            assert url.startswith("https://"), (name, line)
            assert len(quote.split()) <= qg.MAX_QUOTE_WORDS, (name, line)
    methods = (EX / "methods-base" / "METHODS-BASE.md").read_text()
    assert qg.source_ids(methods) == [f"M{i}" for i in range(1, 13)]
    links = (EX / "sources" / "links.md").read_text()
    for url in re.findall(r"\| (https://\S+) \|", methods):
        assert url in links, url
    assert {"past-behaviour", "sample-size"} <= set(re.findall(r"[a-z]+(?:-[a-z]+)*", methods.split("## Rules")[0]))


def test_research_note_has_checked_looking_quotes_and_pasteable_lines():
    note = (EX / "methods-base" / "research" / "car-scent-study.md").read_text()
    quotes = qg.extract_quotes(note)
    assert len(quotes) >= 10
    for line, url, quote in quotes:
        assert url.startswith("https://"), line
        assert len(quote.split()) <= qg.MAX_QUOTE_WORDS, line
    assert "## Could not open" in note and "## Paste into sources/links.md" in note
    assert "## Second search" in note
    # nothing in sources/ or the methods base is the note's own work: it sits in its own file
    assert "research/car-scent-study.md" not in (EX / "methods-base" / "METHODS-BASE.md").read_text()


@pytest.mark.skipif(os.environ.get("WZ_TEST_NETWORK") != "1", reason="opens the real pages; set WZ_TEST_NETWORK=1")
def test_research_note_quotes_are_on_their_pages():
    # a page that fails once is tried once more, as the librarian's rule says: the pages are not ours
    for attempt in range(2):
        problems = qg.quote_problems(EX / "methods-base" / "research" / "car-scent-study.md")
        if not problems:
            break
    assert problems == []


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_sample_project_files_all_pass_their_own_checks(sample):
    methods = (EX / "methods-base" / "METHODS-BASE.md").read_text()
    for prefix in ("", "round1-", "round2-"):
        guide = (sample / f"{prefix}guide.md").read_text()
        review = (sample / f"{prefix}review.md").read_text()
        assert qg.guide_problems(guide) == [], prefix
        assert qg.review_problems(review, guide, methods) == [], prefix
    final = (sample / "review.md").read_text()
    assert re.search(r"^Verdict: PASS", final, re.M)
    assert re.search(r"^Verdict: CHANGES NEEDED", (sample / "round1-review.md").read_text(), re.M)
    assert not [f for r in qg.lint_guide((sample / "guide.md").read_text(), (sample / "jargon.txt").read_text().split())
                for f in r["flags"] if f["level"] == "flag"]


def test_car_scent_review_uses_the_new_labels_and_the_other_flag():
    rounds = "\n".join((CHAIN / f"{p}review.md").read_text() for p in ("round1-", "round2-"))
    assert re.search(r"\|\s*other\s*\|", rounds)
    assert re.search(r"M(7|8|9|10|12)\b", rounds)  # the past-behaviour and sample-size sources are cited


def test_the_three_sample_briefs_carry_their_reports():
    for name in ("01-car-scent-lit", "02-interview-app-mocks", "03-car-scent-gaps"):
        text = (EX / "briefs" / f"{name}.md").read_text()
        report = text.split("## Report", 1)[1]
        outcome = next(l for l in report.splitlines() if l.startswith("- Outcome, one line:"))
        assert len(outcome.split(":", 1)[1].strip()) > 20, name
        assert "/home" + "/" not in text


def test_the_mocks_are_six_phone_pages_with_no_outside_requests():
    mocks = EX / "app" / "mocks"
    screens = sorted(mocks.glob("0[1-6]-*.html"))
    assert len(screens) == 6
    index = (mocks / "index.html").read_text()
    for s in screens:
        assert s.name in index, s.name
        page = s.read_text()
        assert not re.search(r"https?://|<script|\ssrc=", page), s.name
        assert "example" in page.lower()
    for href in re.findall(r'href="([^"#]+)"', index):
        assert (mocks / href).is_file(), href
    assert "Open questions for the owner" in (mocks / "NOTES.md").read_text()


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_sample_is_made_up_and_carries_no_personal_data(sample):
    text = "\n".join(p.read_text() for p in sample.rglob("*.md"))
    assert "made up" in text.lower() or "made-up" in text.lower()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    assert not re.search(r"\b\d{3}[ -]\d{3,4}[ -]\d{4}\b", text)


def test_the_car_scent_study_is_written_fresh():
    # nothing of the field-test owner's flavour study may be in the example (their answers are theirs)
    text = "\n".join(p.read_text(errors="ignore") for p in EX.rglob("*") if p.is_file() and p.suffix in (".md", ".json", ".html", ".txt"))
    assert "flavor" not in text.lower() and "flavour study" not in text.lower()


def test_the_template_layouts_match_what_the_checker_demands():
    layout = (EX / "projects" / "_template" / "guide-layout.md").read_text()
    block = layout.split("```markdown\n", 1)[1].split("\n```", 1)[0]
    for part in ("What we want to learn", "Who to talk to", "Consent and recording script", "Warm-up", "Core questions",
                 "Closing", "How to run this interview", "Notes from the writer"):
        assert part in block


# ---- the setup answers ---------------------------------------------------------------------------------------------
def _setup(tmp_path):
    answers = json.loads((EX / "answers.json").read_text())
    return setup_mode.apply(answers, tmp_path / "ws", git_init=False, simple=True), answers


def test_answers_start_safe(tmp_path):
    cfg, answers = _setup(tmp_path)
    assert cfg.agent()["permission_mode"] == "default"
    assert answers["budget_usd"] <= 5 and answers["accounts"]["main"]["daily_usd"] <= 5
    assert "bypassPermissions" not in (EX / "answers.json").read_text()
    assert set(cfg.roles()) == {"mission-ctl", "librarian", "guide-writer", "reviewer", "designer"}
    assert "builder" not in cfg.roles()
    assert cfg.lead() == "mission-ctl"
    assert not (tmp_path / "ws" / ".wz" / "timers").exists()


def test_the_agent_command_pre_approves_only_the_web_tools_and_the_checker(tmp_path):
    cfg, _ = _setup(tmp_path)
    command = cfg.agent()["command"]
    parts = shlex.split(command)
    assert len(parts) == 3 and parts[:2] == ["claude", "--allowedTools"]
    assert parts[2] == "WebSearch,WebFetch,Bash(python3 tools/qg.py *)"
    for broad in ("Bash,", "Bash(python3:*)", "python3*", "Write", "Edit"):
        assert broad not in command
    # the rule must match a command that starts `python3 tools/qg.py ` and nothing that merely names the file
    rule = parts[2].split(",")[2]
    assert rule.startswith("Bash(") and rule.endswith(" *)")
    prefix = rule[len("Bash("):-len(" *)")]
    assert prefix == "python3 tools/qg.py"

    def allowed(cmd):
        return cmd.startswith(prefix + " ") and not any(c in cmd for c in ";&|`$<>\n")
    assert allowed("python3 tools/qg.py sources")
    assert not allowed("python3 -c \"open('x','w').write('A')\" tools/qg.py")
    assert not allowed("python3 tools/qg.py lint x.md; touch y")


def test_only_the_librarian_may_search_and_fetch(tmp_path):
    cfg, _ = _setup(tmp_path)
    assert cfg.role("librarian")["web"] == ["WebSearch", "WebFetch"]
    assert [r for r, v in cfg.roles().items() if v["web"]] == ["librarian"]
    env = lambda role: {"WZ_ROLE": role, "WZ_CONFIG": str(cfg.path)}
    for tool, args in (("WebSearch", {"query": "x"}), ("WebFetch", {"url": "https://example.com"})):
        assert guard.main(payload(tool, cfg.root, **args), env("librarian")) == 0
        for role in ("designer", "guide-writer", "reviewer", "mission-ctl"):
            assert guard.main(payload(tool, cfg.root, **args), env(role)) == 2, (role, tool)


def test_roles_have_plain_charters_that_name_the_checker(tmp_path):
    cfg, _ = _setup(tmp_path)
    for role, needle in (("librarian", "qg.py quotes"), ("guide-writer", "qg.py guide-check"),
                         ("reviewer", "qg.py review-check"), ("mission-ctl", "new-project")):
        charter = cfg.charter_path(role).read_text()
        assert needle in charter, role
    assert "Never invent a reference" in cfg.charter_path("librarian").read_text()
    assert "Never edit the guide" in cfg.charter_path("reviewer").read_text()
    for role in ("librarian", "guide-writer", "reviewer"):
        assert cfg.role(role)["model"] == "sonnet"


def _write(cfg, role, rel):
    env = {"WZ_ROLE": role, "WZ_CONFIG": str(cfg.path)}
    return guard.main(payload("Write", cfg.root, file_path=str(cfg.root / rel), content="x"), env)


def test_each_helper_may_write_only_its_own_files(tmp_path):
    cfg, _ = _setup(tmp_path)
    allowed = {
        "librarian": ["methods-base/METHODS-BASE.md"],
        "guide-writer": ["projects/p/guide.md", "projects/p/jargon.txt"],
        "reviewer": ["projects/p/review.md"],
        "mission-ctl": ["projects/p/brief.md", "projects/p/audience.md", "projects/p/docs/notes.md", "DECISIONS.md"],
    }
    everything = [f for files in allowed.values() for f in files] + ["tools/qg.py", "sources/links.md", "answers.json"]
    for role, files in allowed.items():
        for rel in everything:
            want = 0 if rel in files else 2
            assert _write(cfg, role, rel) == want, (role, rel)


def test_example_answers_make_a_workspace_via_the_cli(tmp_path, capsys):
    from wz import cli
    rc = cli.main(["init", "--simple", "--answers", str(EX / "answers.json"), "--dir", str(tmp_path / "ws"), "--no-git"])
    assert rc == 0
    cfg = config.load(tmp_path / "ws" / "wz.toml")
    assert cfg.validate() == []
    assert "no timers are installed" in capsys.readouterr().out


# ---- the research-and-mocks chain ---------------------------------------------------------------------------------
def _with_builder(tmp_path):
    answers = json.loads((EX / "answers.json").read_text())
    answers["roles"]["builder"] = answers["roles_later"]["builder"]
    return setup_mode.apply(answers, tmp_path / "ws6", git_init=False, simple=True)


def _example_path(pattern):
    return pattern.replace("**", "x/y").replace("*", "x")


def test_the_config_parses_and_six_charters_are_written_once_the_builder_is_switched_on(tmp_path):
    cfg = _with_builder(tmp_path)
    assert cfg.validate() == []
    assert set(cfg.roles()) == {"mission-ctl", "librarian", "guide-writer", "reviewer", "designer", "builder"}
    assert len(list(cfg.charter_path("builder").parent.parent.glob("*/CHARTER.md"))) == 6
    for name, r in cfg.roles().items():
        for pat in r["owns"].get("workspace", []):
            assert guard.owners_of(cfg, "workspace", _example_path(pat)) == [name], (name, pat)
    for pat in cfg.role("builder")["owns"]["workspace"]:
        assert not config_glob(pat, "app/mocks/01-x.html") and not config_glob("app/mocks/**", _example_path(pat))


def config_glob(pattern, path):
    from wz.util import glob_match
    return glob_match(path, pattern)


def test_the_shipped_setup_has_five_charters_and_the_designer_owns_only_the_mocks(tmp_path):
    cfg, _ = _setup(tmp_path)
    assert len(list(cfg.charter_path("designer").parent.parent.glob("*/CHARTER.md"))) == 5
    assert cfg.role("designer")["owns"] == {"workspace": ["app/mocks/**"]}


def test_the_guard_keeps_each_helper_in_its_lane(tmp_path):
    cfg, _ = _setup(tmp_path)
    assert _write(cfg, "designer", "projects/x/guide.md") == 2
    assert _write(cfg, "designer", "projects/x/review.md") == 2
    assert _write(cfg, "designer", "app/mocks/01-before-you-start.html") == 0
    assert _write(cfg, "librarian", "sources/links.md") == 2
    assert _write(cfg, "librarian", "projects/x/guide.md") == 2
    assert _write(cfg, "librarian", "methods-base/research/car-scent-study.md") == 0
    assert _write(cfg, "guide-writer", "app/mocks/index.html") == 2
    assert _write(cfg, "reviewer", "methods-base/research/car-scent-study.md") == 2
    assert _write(cfg, "mission-ctl", "ledgers/FOLLOWUPS.md") == 0
    assert _write(cfg, "mission-ctl", "app/mocks/index.html") == 2
    assert _write(cfg, "mission-ctl", "wz.toml") == 2


def test_the_builder_is_refused_the_mocks_when_it_is_switched_on(tmp_path):
    cfg = _with_builder(tmp_path)
    assert _write(cfg, "builder", "app/mocks/01-before-you-start.html") == 2
    assert _write(cfg, "builder", "app/src/main.txt") == 0


def test_serve_dry_run_starts_only_the_first_job_of_each_lane_and_names_what_waits(tmp_path):
    from wz import jobs, worker
    cfg, _ = _setup(tmp_path)
    lit = jobs.add(cfg, "librarian", "Do brief 01.", priority=10, evidence="the note exists")
    base = jobs.add(cfg, "librarian", "Read what is new in sources/.", priority=20, after=lit["id"])
    jobs.hold(cfg, base["id"], "the owner picks sources")
    guide = jobs.add(cfg, "guide-writer", "Write the guide.", priority=30, after=base["id"])
    jobs.hold(cfg, guide["id"], "audience.md not filled in yet")
    review = jobs.add(cfg, "reviewer", "Review the guide.", priority=40, after=guide["id"])
    mocks = jobs.add(cfg, "designer", "Do brief 02.", priority=20)
    msgs = []
    worker.serve(cfg, dry_run=True, say=msgs.append)
    started = [m for m in msgs if "would start" in m]
    assert sorted(m.split("would start ")[1].split(":")[0] for m in started) == sorted([lit["id"], mocks["id"]])
    assert any(f"{review['id']} waits for {guide['id']}" in m for m in msgs)
    for j in (base, guide, review):
        assert jobs.get(cfg, j["id"])["status"] in ("held", "queued")
    assert not (cfg.root / ".wz" / "timers").exists()


def _lead_charter(tmp_path):
    cfg, _ = _setup(tmp_path)
    return " ".join(cfg.charter_path("mission-ctl").read_text().split())


def test_the_lead_charter_keeps_a_queued_jobs_done_check_in_step_with_its_brief(tmp_path):
    c = _lead_charter(tmp_path)
    assert "When a brief changes while a job that uses it is still queued or held, change the job's evidence text to match" in c
    assert "`wz job cancel <id>`" in c and "add the job again with the new `--evidence`" in c


def test_the_lead_charter_closes_or_queues_every_follow_up_it_reads(tmp_path):
    c = _lead_charter(tmp_path)
    assert "close or queue every follow-up that report raised in ledgers/FOLLOWUPS.md" in c
    assert "mark the row done and name the job that did it, queue it as a job, or write `owner decides:`" in c


def test_the_lead_charter_proposes_a_helper_instead_of_doing_unowned_work(tmp_path):
    c = _lead_charter(tmp_path)
    assert "A request that no helper owns" in c and "proposed helper or rule change" in c
    assert "changes wz.toml themselves" in c


def test_the_lead_charter_reads_the_mode_and_runs_the_chain_with_holds_and_serve(tmp_path):
    c = _lead_charter(tmp_path)
    assert "read `permission_mode` in wz.toml yourself" in c and "You may not edit wz.toml" in c
    assert "`wz job hold <id> --why" in c and "run `wz serve` again after each job ends" in c
    assert "no timers" in c


def test_the_librarian_and_reviewer_charters_carry_the_new_labels_and_rules(tmp_path):
    cfg, _ = _setup(tmp_path)
    lib = " ".join(cfg.charter_path("librarian").read_text().split())
    assert "past-behaviour, sample-size" in lib
    assert "Write what you find only to methods-base/research/<project>.md, never to sources/ or METHODS-BASE.md" in lib
    assert "The owner decides what moves into sources/" in lib
    rev = " ".join(cfg.charter_path("reviewer").read_text().split())
    assert "past-behaviour or sample-size" in rev and "with the flag 'other'" in rev
    assert "long, other" in rev
    gw = " ".join(cfg.charter_path("guide-writer").read_text().split())
    assert "methods-base/research/<name>.md exists, read it before writing" in gw

