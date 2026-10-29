# Build and release

## Rings

```toml
[rings]
order = ["lab", "dev", "prod"]
sign = ["prod"]                     # the owner signs every move onto these

[rings.dev]
gates = ["./ci/smoke.sh \"$WZ_ARTIFACT\"", "./ci/contract-check.sh"]
deploy = "./ops/deploy.sh dev \"$WZ_ARTIFACT\""
rollback = "./ops/rollback.sh dev"
health_url = "http://dev.example.internal/healthz"

[release]
pin_params = ["sample_hz", "threshold"]
flag_registry = "flags.toml"
flag_sources = ["app/src/**/*.py"]
```

- **lab** is where anything goes: benches, branches, experiments. **dev** is integrated, gated and rehearsed.
  **prod** moves only on the owner's sign.
- `wz ring pin dev build/app-1.4.tar --param sample_hz=50` records the artifact's sha256 and its parameters in
  `status/pins/dev.json`, beside the previous pin, which is the one rollback returns to.
- `wz ring gate dev` checks the file still hashes to the pin. It runs each gate with `WZ_ARTIFACT`,
  `WZ_ARTIFACT_SHA256`, `WZ_RING` and `WZ_PIN_PARAMS`, hashes the file again afterwards, and writes
  `status/releases/<sha12>/dev-gate.json`. A gate reads the artifact, never its tag or its label.
- **Pins carry parameters only.** A pin may set only the names listed in `pin_params`, and only to single values.
  The hard invariants (limits, safety rules, protocol checks) live in the code, where review and tests see them.
- `wz ring rehearse dev` runs deploy, rollback, deploy on a ring that needs no sign. The revert path has then run
  before the day it is needed.
- `wz ring read prod code.version` is what "live" means. It reads the field from the running ring and keeps the
  value and read time under `status/live/`. "Merged", "published" and "tests green" are not live.

## Interface contract

One contract file per interface between components. It changes first, in the same change as the code, only by
adding, and carries a version that does not move for additive changes. The `software` pack's rule makes this the
role's duty, and the merge step's checks are where a contract test belongs.

## Feature flags

Every flag goes in `flags.toml` with an owner and `default = false`. A flag ships on only with
`release_default = true` and `decision = "D-n"` naming a row in `DECISIONS.md`. `wz flags check` fails on an
unregistered flag, a missing owner, or a default-on flag without a decision. Run it in CI and before every cut.

## Cut, sign, presign window

1. `wz hold add app --level FREEZE --expires 4h "presign window for 1.4"`. The merge step leaves the store alone,
   so the candidate cannot move.
2. `wz promote app` asks the owner to sign moving main to that exact integration commit (a sha, not a branch).
3. The owner signs (`wz sign approve`, or the approval page with their PIN). `wz sign run` performs it once. It
   refuses while any BLOCKS or INCONCLUSIVE hold names the store, the commit or the ring.
4. Clear the freeze once the sign is used: `wz hold clear <id> --decision D-n`.

## Holds

`wz hold add <ref> --level BLOCKS --evidence <file> "<one sentence>" --expires 3d`:
- **BLOCKS** stops promote and any signed act on its ref.
- **INCONCLUSIVE** does the same: an unfinished check is not a pass.
- **NOTE** is shown and never blocks.
- **FREEZE** is a presign window.

Every hold expires. An expired, uncleared hold stops blocking and becomes a watchdog alert, so the lead decides
whether it still holds. Clearing a hold needs a decision row.

## The queue, kept honest

| Process | Command | Notes |
|---|---|---|
| merge bot and CI queue | `wz merge` (every 5 min) | Ownership backstop, then the batch queue (`wz/mergeq.py`): up to `merge_batch` branches (default 8) are stacked on the integration tip in a throwaway worktree and the store's checks run once on the stack. Green: one compare-and-swap lands them all. Red: a binary search over the stack finds the first branch that turns it red (about log2 n more check passes); that branch is bounced alone (`red`), the green part below it lands, the part above it is stacked again. A branch that does not merge is bounced alone (`conflict`). If the integration tip itself fails the checks, nobody is blamed (`base-red`) and nothing moves. A branch that is red only together with an earlier one in the same batch is blamed on the later one. Store keys: `merge_batch` (1 = one at a time), `merge_gate_runs` (check passes per call, default 24; branches not reached keep waiting). |
| job timeouts and reminting | `wz job remint <id> [--timeout]` | The old job records `reminted_as`. Queued or held dependents are re-pointed to the new id. A timed-out job gets twice the timeout. |
| follow-ups as held jobs | `wz job release <id>` | Each follow-up a finished job declares is also written to `FOLLOWUPS.md`, and becomes a held job that names its parent (`followup_of`). At most 5 per finished job; a follow-up of a follow-up, an unknown role, or a task already queued or held for that role is a ledger row only. The job record lists both (`followup_jobs`, `followups_ledger_only`). Release a held one to run it, or cancel it. |
| backlog refill | `wz backlog refill` | Open defect and follow-up rows land once in `roles/<role>/BACKLOG.md`. |
| focus and prune | `wz prune` / `--apply` | `[focus] patterns`, `min_priority`, `hold_days`, `jaccard`. Never touches running jobs. |
| holds with expiry | `wz hold` | above |
| andon halt | `wz halt <role\|all>` | Anyone pulls it. Only the lead lifts it. A crossed bench limit pulls it too. |
| budget controller | `[budget] daily_usd`, `[accounts.<a>] daily_usd` | Serve starts nothing past a cap. Running jobs finish. |
| watchdog | `wz watchdog` (every 10 min) | LOST, OVERDUE, STUCK, ORPHANED, IDLE, UNSIGNED, HAND, LEASE and HOLD alerts. |
| nightly jobs | `[[nightly]] role, task, priority, timeout, lease` | Queued once per day at `[project] nightly_time`. |
| daily sync and digest | `wz sync`, `wz digest` | The lead's section first. At most three asks, and the lead's own errors named. |
| status dashboard | `wz status --html status/dashboard.html` | A static page. Publish it wherever the owner reads. |

## Continuity and audit

- **STATE.md and LESSONS.md per role.** Every job prompt includes both. A job ends by rewriting STATE.md whole (one
  screen) and adding one LESSONS.md line for each failure the next job should not repeat.
- **Lead handoff.** When the lead's context nears its limit, it writes `roles/<lead>/HANDOFF.md`. A fresh lead
  session reads it first, then deletes it.
- **Auditor pass.** A decision row or an outward claim stands only once `ledgers/AUDITS.md` has a pass row naming
  it, written by a role on the `auditor` pack. That role re-derives every number and fixes nothing it audits.

## Post-run and field-test review

`wz review collect <session dir>` does the following:
- copies the session into `runs/<name>/session/`;
- runs `[review] metrics`, a command with `{session}` and `{out}` that writes `metrics.json`;
- drafts `REVIEW.md` from `runs/TEMPLATE.md` (or the built-in template), with the metrics and the file they came from.

The draft has one empty section, the owner's words, which only the owner fills (`wz review words <name> "..."`).
`wz review list` shows the drafts still waiting for them.
