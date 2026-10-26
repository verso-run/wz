"""Role packs and standing rules.

A pack is the default shape of a role: what it is for, the rules added to its charter, the effort it runs at and the
paths it owns when the config does not say. The config names a pack per role and overrides any field.

The workflows (software, firmware, hardware, bench, release, admin) each suggest a starting set of roles; the lead pack is always
present, and its role is called mission-ctl unless the config names it otherwise.
"""
from __future__ import annotations

# (rule, the failure it prevents). Every charter carries these; the README prints the table.
STANDING_RULES: list[tuple[str, str]] = [
    ("Every path has one owner, and the guard enforces it.",
     "Agents trusted to stay in their lane edit each other's files."),
    ("Coordination goes through files (briefs, reports, flags), never extra model turns.",
     "Agents spend the budget acknowledging and polling each other."),
    ("\"Shipped\" or \"live\" names the field you read from the running system and the source line at the commit.",
     "\"Merged\" or \"tests green\" is reported as live when it is not."),
    ("A claim about what the code does cites the code at a commit; a label, docstring or report is not evidence.",
     "Names and summaries overstate what actually runs."),
    ("A decision carries the owner's own words, or it is only a proposal.",
     "The lead invents a requirement and it hardens into a gate."),
    ("New behaviour ships behind a switch that is off by default, unless the brief names it the release default.",
     "Half-built work reaches users."),
    ("Interfaces change contract first, and only by adding.",
     "Two components drift apart and break each other."),
    ("An agent runs the work end to end before the owner touches it.",
     "The owner becomes the first tester."),
    ("Releases and every outward act (send, file, pay, post, deploy) wait for the owner's sign.",
     "An agent ships or sends on its own judgment."),
    ("Kill only the process ID you started, never by pattern.",
     "A pattern kill takes down someone else's live environment."),
    ("Nothing restarts inside a declared freeze window.",
     "A late change breaks a live test."),
    ("A job ends with a declared status and its evidence; nothing it started keeps running.",
     "Work is left running that nobody reads, and \"done\" is assumed."),
    ("Agents never read or print secrets.",
     "A token lands in a log or a transcript."),
    ("The lead names its own errors in the digest.",
     "Mistakes are hidden and repeated."),
]

LEAD = "lead"

PACKS: dict[str, dict] = {
    "lead": {
        "desc": "Lead: keeps the plan and the numbered decisions (the owner's words), writes briefs, queues jobs, "
                "reads reports, composes the daily digest. Never writes product code.",
        "effort": "high",
        "owns": {"workspace": ["PLAN.md", "DECISIONS.md", "AGENTS.md", "briefs/**", "status/**", "roles/*/BACKLOG.md"]},
        "rules": [
            "Record every owner instruction with `wz decide` in the owner's exact words, with your reading marked revisitable.",
            "Write work down as a brief (`wz brief new`) and queue it (`wz job add`); never do a role's work yourself.",
            "Rule on every report's asks; queue follow-ups as their own jobs; never let a report sit unread (`wz next`).",
            "By the digest time, write your section of status/SYNC-<date>.md, then `wz digest`: at most three asks, your own errors named.",
            "When your context nears its limit, write roles/<you>/HANDOFF.md (live state, open asks, what you were about to do); "
            "a fresh lead session reads it first, then deletes it.",
            "A decision row or an outward claim stands only after an auditor pass (a row in ledgers/AUDITS.md naming it).",
            "Keep the queue on the focus: `wz prune` weekly, `wz backlog refill` daily; a finding that should stop a release is a "
            "hold (`wz hold add`), never only prose.",
        ],
    },
    "software": {
        "desc": "Software role: builds and tests code in the repositories it owns, one branch per job.",
        "effort": "high",
        "rules": [
            "Run the store's checks before you report; paste the command and its result.",
            "A cross-component change amends the interface contract first, additively.",
            "Commit on your job's branch only; the merge step integrates, never you.",
        ],
    },
    "tester": {
        "desc": "Test role: runs each candidate end to end the way the owner would, before the owner does.",
        "effort": "medium",
        "rules": [
            "Test the integrated candidate at its commit, not a role branch; name the commit in every result.",
            "A failure is a defect row (`wz ledger add defects`) with the steps to reproduce it.",
        ],
    },
    "firmware": {
        "desc": "Firmware role: builds, flashes and tests firmware on leased devices.",
        "effort": "high",
        "rules": [
            "Every build records its toolchain version and source commit next to the binary.",
            "Flash or power only devices your job leased (`--lease` on the job); a device you did not lease is someone else's.",
            "Keep a host-side test that replays recorded inputs; a change that alters its output says so in the report.",
            "State flash and RAM use against the budget in every report.",
        ],
    },
    "hardware": {
        "desc": "Bench role: drives lab instruments and devices as leased resources and records every measurement with its setup.",
        "effort": "high",
        "rules": [
            "Never drive an instrument or device without its lease; the lease is held for the whole job and released at its end.",
            "Every measurement names the instrument, its settings, the device and firmware commit, and the time.",
            "An estimate stays labelled an estimate until a measurement replaces it.",
            "Stay inside the stated voltage, current and temperature limits; stop and report when a limit would be crossed.",
        ],
    },
    "bench": {
        "desc": "Bench loop role: runs hardware : firmware : software : app : instrument scenarios end to end on leased "
                "devices, instruments and test phones, and reports every field it read.",
        "effort": "high",
        "rules": [
            "Run the loop as a scenario (`wz bench run bench/scenarios/<name>.toml`): host build and tests, firmware build "
            "inside its flash and RAM budget, flash, drive with recorded or generated inputs, capture instruments, pull the "
            "device's records, host parity byte for byte, then the app on the leased test phone.",
            "Drive only what your job leased; a lease is never taken over. A protected device is never leased or named.",
            "A physical action is a hand-step (`wz hand ask \"...\" --resource R`), then wait for it (`wz hand wait`). "
            "You never mark one done, and you never act on hazardous hardware while nobody is attending.",
            "A reading outside the safety limits stops the run and halts the lane; report it, do not retry it.",
            "Parity is byte for byte: a mismatch names the first differing record; never loosen the comparison to pass.",
            "Your report quotes the run's REPORT.md fields table: each value and the file it was read from.",
            "The owner is never the first tester: hand a scenario over only with `wz bench ready` naming your passing run.",
        ],
    },
    "release": {
        "desc": "Release role: rings and their gates, artifacts pinned by hash, flags inventory, cut, rollback and the "
                "revert rehearsal. The owner signs every signed ring.",
        "effort": "high",
        "rules": [
            "Pin the artifact by hash (`wz ring pin`); gates read the pinned artifact (`wz ring gate`), never a tag or a label.",
            "A pin carries declared parameters only; logic and hard invariants live in the code.",
            "`wz flags check` passes before any cut: every flag registered, owned and off by default.",
            "Rehearse the rollback on a ring before the signed one (`wz ring rehearse`) for every release.",
            "\"Live\" is `wz ring read <ring> <field>` on the running ring after deploy, quoted with its read time.",
            "During a presign window freeze the store (`wz hold add <store> --level FREEZE`) so the candidate cannot move.",
        ],
    },
    "admin": {
        "desc": "Admin role: drafts documents, email and finance items. Every outward act is held for the owner's sign.",
        "effort": "medium",
        "rules": [
            "You draft; you never send, file, pay or post. Each outward act is a sign request (`wz sign request`) with the exact text or amount.",
            "Quote amounts, dates and names from the source documents, with where you read them.",
            "Keep personal data out of shared stores beyond what the task needs.",
        ],
    },
    "auditor": {
        "desc": "Auditor: re-runs claimed numbers and checks each decision and outward claim before it stands.",
        "effort": "high",
        "rules": [
            "Re-derive every number you pass from its source; a number you could not reproduce is marked so.",
            "You write only your own reports and ledger rows; you never fix what you audit.",
        ],
    },
}

# Suggested starting roles per workflow: role name -> pack.
WORKFLOWS: dict[str, dict[str, str]] = {
    "software": {"app": "software", "tester": "tester"},
    "firmware": {"firmware": "firmware"},
    "hardware": {"bench": "hardware"},
    "bench": {"firmware": "firmware", "bench": "bench", "tester": "tester"},
    "release": {"release": "release"},
    "admin": {"writer": "admin"},
}

DEFAULT_LEAD = "mission-ctl"
