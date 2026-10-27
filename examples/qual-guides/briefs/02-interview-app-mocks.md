# Brief 02 — Phone mocks of an interview companion app

**Role:** designer · **Written:** 2026-10-26 · **Blocking for:** the builder (not set up; it waits for the owner to sign off the mocks)
**Decision:** the owner wants to see what a small phone app that sits beside the person running an interview could look like, before deciding whether to build it. Pictures first; no working app.

## Read first, in order
1. Your charter (roles/designer/CHARTER.md) and notes (roles/designer/STATE.md).
2. projects/_template/guide-layout.md (the parts every guide has) and projects/larkspur-tool-library/guide.md (a finished guide, to take real wording from). The car scent guide is not written yet; do not wait for it.
3. projects/car-scent-study/brief.md (who runs the interviews and how much experience they have).

## What done means
app/mocks/ holds six phone-sized screens as plain web pages, an index.html that links to all six, and NOTES.md with your questions for the owner. Every link in index.html opens a file that exists.

## The six screens
1. **Before you start**: a short checklist drawn from the guide's "how to run this interview" card (recorder charged, a quiet place, the consent words to hand).
2. **Consent**: the read-aloud consent script from the guide, big type, with a place to note the person's yes.
3. **Question**: one question at a time with its probes under it, the minutes left for this part, and the next part.
4. **Quick answers**: a few facts to note fast (for example the last scent bought, where, how long ago), as buttons the interviewer taps without looking.
5. **Wrap-up**: the closing question, the thank-you, what happens next.
6. **Tally**: after several conversations, how many people said each thing, with the quotes behind each count.

## Constants
| name | value | where it comes from |
|---|---|---|
| width | about 390 px | a phone held upright |
| outside requests | none | charter |
| write only | app/mocks/** | your charter |

## Ladder (in order; stop and report if a rung fails its acceptance)
1. Draw the six screens. **Accept:** six HTML files, numbered in the order above, each opens without a network.
2. Write index.html and NOTES.md. **Accept:** index links to all six; NOTES.md lists at most six questions for the owner.
3. Check the links. **Accept:** you name the check you ran.

## Critical path and fallback
- Critical path: 1, 2, 3.
- If a screen needs wording the sample guide does not have, write it, mark it as example content, and say so in NOTES.md.

## Not yours
- Any working app, and everything outside app/mocks/.
- The guide and the review for any project.

## Report (the role fills this in; the lead reads it)
- Outcome, one line: six phone screens, index.html and NOTES.md written in app/mocks/; all links resolve.
- Acceptance per rung (number, and the command or file that shows it):
  1. app/mocks/01..06-*.html, each with inline CSS only; `grep -lE 'https?://|<script|src=' *.html` printed nothing (no outside requests).
  2. app/mocks/index.html links all six; NOTES.md lists six owner questions.
  3. Check run: `grep -ho 'href="[^"]*"' *.html | sort -u` listed 7 targets (the six screens and index.html); `ls` shows every one in app/mocks/.
- Deviations from the ladder, and why: wording is from the Larkspur sample guide because the car scent guide does not exist yet (brief allows it). Quick-answers rows and tally numbers are invented and marked. A Python generator needed an approval no one can give in a job, so I wrote the files by hand with Write; the generator is unused in scratch.
- Interface or contract changes (additive only): none.
- What in the docs was wrong: nothing found. The brief's example for screen 4 (scent facts) does not match the Larkspur sample, so I used tool-getting facts.
- Asks (owner / lead): owner: open app/mocks/index.html and comment; answer the six questions in NOTES.md.
- Follow-ups (one job each): none.
