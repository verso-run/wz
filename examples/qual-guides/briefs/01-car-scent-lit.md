# Brief 01 — Reading for the car scent study

**Role:** librarian · **Written:** 2026-10-26 · **Blocking for:** the guide for projects/car-scent-study (the job after the owner picks sources)
**Decision:** the owner wants the guide to rest on advice about asking people what they did, not what they would buy, and about how many conversations are enough.

## Read first, in order
1. Your charter (roles/librarian/CHARTER.md) and notes (roles/librarian/STATE.md).
2. projects/car-scent-study/brief.md, audience.md and docs/draft-questions.md (the questions the owners wrote, several of which ask people to predict what they would buy).
3. methods-base/METHODS-BASE.md (what the base already says, so you do not repeat it) and sources/links.md.

## What done means
methods-base/research/car-scent-study.md exists and answers the five questions below, each with at least one source you opened, its link, its author, its licence as the page states it, a plain summary and a checked quote; `python3 tools/qg.py quotes methods-base/research/car-scent-study.md` passes; the note ends with the lines the owner could paste into sources/links.md. You do not touch sources/ or METHODS-BASE.md.

## The five questions
1. Why is "would you buy it?" a poor question, and what does published advice say to ask instead (what people did and bought)?
2. How many conversations are enough for a small exploratory study ahead of one cheap decision? Is six to eight believable?
3. How do you ask about an everyday habit (what did you do the last time...) without leading, and how far back can people reliably remember?
4. How do people talk about smell or other hard-to-describe senses in interviews, and what helps them find words without being given the words?
5. How should a small shop recruit its own past customers for interviews without only hearing from the happy ones?

## Constants
| name | value | where it comes from |
|---|---|---|
| web search | allowed for this brief | wz.toml, librarian `web` |
| write only | methods-base/research/car-scent-study.md | your charter |
| sources to find | up to eight, freely readable | this brief |

## Ladder (in order; stop and report if a rung fails its acceptance)
1. Search and open pages for each question. **Accept:** at least one opened source per question, or the question marked "no source found".
2. Write the note. **Accept:** every source has link, author, licence as stated, summary and a quote.
3. Check the quotes. **Accept:** `python3 tools/qg.py quotes methods-base/research/car-scent-study.md` passes.
4. End with paste-in lines for sources/links.md and a list of what you could not open.

## Critical path and fallback
- Critical path: 1, 2, 3.
- If a page will not open or a quote will not match, drop that quote and say so; do not paraphrase it as a quote.

## Not yours
- sources/ and methods-base/METHODS-BASE.md (the owner decides what moves into sources/; the next job updates the methods base).
- The guide and the review.

## Report (the role fills this in; the lead reads it)
- Outcome, one line: done (job-0005): methods-base/research/car-scent-study.md written, 8 sources opened, all quotes machine-checked. Web access worked this time (first search succeeded).
- Acceptance per rung (number, and the command or file that shows it): 1 met for Q1, Q2, Q3, Q5; Q4 has sources on why smell is hard but none on an interview method (marked "no source found" there). 2 met. 3 met: `python3 tools/qg.py quotes methods-base/research/car-scent-study.md` -> "every quoted line was found on its page". 4 met: paste-in lines 7-13 and a "Could not open" list at the end of the note.
- Deviations from the ladder, and why: Q2 rests on the abstract page only (full Guest paper and the 2016 follow-up returned 403/404). Q3 has no firm recall limit; the note says so. Q5 has one source, about surveys, not interviews.
- Interface or contract changes (additive only): none.
- What in the docs was wrong: nothing found. Quotes had to be re-pointed once: a quote sat under the wrong link, and a Majid line was not on the KPBS page.
- Asks (owner / lead): owner: choose which of lines 7-13 move into sources/links.md. Lead: nothing.
- Follow-ups (one job each): librarian, after the owner moves sources, add past-behaviour, sample-size and smell rules to METHODS-BASE.md; optionally a second literature search for Q4 (interview method for smell) and Q5 (recruiting for small interview studies).
