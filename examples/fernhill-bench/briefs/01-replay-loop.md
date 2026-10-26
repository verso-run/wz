# Brief 01 — replay loop on board-a (role: bench)

**Why:** the valve hysteresis change must behave the same on the board as on the host, before the owner waters
anything with it.

**Task:** run `scenarios/replay.toml` end to end on board-a and phone-b, at the job's commit:
`wz bench run scenarios/replay.toml`. The run asks one hand-step (analyser leads on). Wait for it. Do not answer it.

**Evidence of done:**
- the run's verdict is `pass`;
- `parity.records_equal` is N/N;
- `budget.flash` and `budget.ram` are within `[bench.budget.default]`;
- `analyser.volts` is inside `[bench.safety.limits]`;
- `wz bench ready scenarios/replay.toml` names this run.

**Out of scope:** changing the limits, the scenario or the comparison. A failure is reported, not worked around.

**Leases:** board-a, phone-b, analyser. The job is queued with
`wz job add bench "<task>" --lease board-a --lease phone-b --lease analyser`.

## Report

(the bench role fills this in: the run id, the verdict, and the "Fields read" table from the run's REPORT.md,
copied as it is; any hand-step and how it was answered; deviations; follow-ups as ledger rows)
