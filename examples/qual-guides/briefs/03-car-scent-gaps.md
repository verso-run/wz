# Brief 03 — Gaps left by the first search

**Role:** librarian · **Written:** 2026-10-26 · **Blocking for:** the guide for projects/car-scent-study
**Decision:** D-2 (the owner kept six of the seven sources from brief 01). The first note ended with gaps; this brief closes what can be closed from freely readable pages.

## Read first, in order
1. Your charter (roles/librarian/CHARTER.md) and notes (roles/librarian/STATE.md).
2. methods-base/research/car-scent-study.md (the first note; its "Not found" lines are the gaps) and the Report of brief 01.
3. projects/car-scent-study/brief.md and audience.md.

## What done means
methods-base/research/car-scent-study.md has a new section "Second search" that takes each gap below and either gives a source you opened (link, author, licence as the page states it, plain summary, checked quote) or says "no source found". `python3 tools/qg.py quotes methods-base/research/car-scent-study.md` passes. You touch no other file except this brief's Report.

## The gaps
1. An interview method for smell or other hard-to-name sensations: how to help people find words without giving them the words.
2. Recruiting for a small interview study from a shop's own customer list: how to avoid hearing only from the happy ones.
3. How many interviews for a decision that costs about £2,500, and what the 2016 follow-up to Guest, Bunce and Johnson says if any freely readable page gives it.
4. A freely readable page on how far back people can recall an ordinary, low-interest purchase.
5. Who to talk to first. The owner asks: "Should Rowan also talk to people who looked at the shop and did not buy, and how would we find them?" Find advice on choosing whom to interview when a shop does not yet know its customers, and on reaching people who never bought from it.

## Constants
| name | value | where it comes from |
|---|---|---|
| web search | allowed for this brief | wz.toml, librarian `web` |
| write only | methods-base/research/car-scent-study.md | your charter |
| sources already in sources/ | 7 to 12 | D-2 |

## Ladder (in order; stop and report if a rung fails its acceptance)
1. Search for each gap. **Accept:** each gap has a source you opened or "no source found".
2. Write the section. **Accept:** every source has link, author, licence, summary and a quote.
3. Check the quotes. **Accept:** `python3 tools/qg.py quotes methods-base/research/car-scent-study.md` passes.

## Critical path and fallback
- Critical path: 1, 2, 3.
- Do not repeat a source already in the note or in sources/; say "already have" instead.

## Not yours
- sources/ and methods-base/METHODS-BASE.md.
- The guide and the review.

## Report (the role fills this in; the lead reads it)
- Outcome, one line: "Second search" added; gaps 2, 3 and 5 got opened sources (S1 to S4); gaps 1 and 4 say "no source found".
- Acceptance per rung (number, and the command or file that shows it): 1 and 2: methods-base/research/car-scent-study.md, section "Second search"; 3: `python3 tools/qg.py quotes methods-base/research/car-scent-study.md` printed "every quoted line was found on its page".
- Deviations from the ladder, and why: none. Gap 3's 2016 Guest follow-up stayed 403; a different 2016 paper (Hennink, Kaiser, Marconi) stands in and is labelled so.
- Interface or contract changes (additive only): none.
- What in the docs was wrong: the brief names the 2016 follow-up to Guest, Bunce and Johnson; the SAGE DOI in the first note (1525822X16640447) is by Guest, Namey and McKenna, which I could not open to confirm what it covers.
- Asks (owner / lead): owner decides whether links 14 and 15 move into sources/links.md. Gap 4 has no usable page; BLS and Boston Fed PDFs opened as unreadable data.
- Follow-ups (one job each): none required; optional: read the BLS recall-period PDF as text.
