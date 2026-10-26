# The layout every review follows

The reviewer copies this layout; `python3 tools/qg.py review-check` checks it.

```markdown
# Review: <project name> discussion guide

Verdict: CHANGES NEEDED        <- or: PASS

<three or four plain lines: what is good, what must change>

## Findings
| Where | Question | Flag | Why | Method source | Suggested rewrite |
|---|---|---|---|---|---|
| Q2 | "<the question, word for word>" | double-barrelled | <plain reason> | M4 | "<a better question>" |

## Goals and questions
<for each goal in part 1, the questions that would answer it, or "no question covers this">

## Checked and fine
<ids of the questions and probes you read and found fine>

## Checker flags I dismissed
<each id, with the reason>

## What I could not check
<anything the methods base does not cover>
```

Flags are one of: leading, double-barrelled, jargon, yes/no, long. "Method source" is an M-number from the table at
the top of methods-base/METHODS-BASE.md, or the words "not covered by the methods base".
