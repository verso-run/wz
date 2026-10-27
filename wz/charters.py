"""The charter generator: roles/<role>/CHARTER.md for every role, from wz.toml, the role packs and the rules.

Also writes AGENTS.md (who owns what, one table), each role's STATE.md, LESSONS.md and BACKLOG.md when missing, and the hook
settings every role session runs with (.wz/role-settings.json). Re-run it after any change to wz.toml: `wz charters`.
"""
from __future__ import annotations

import shlex
from pathlib import Path
from string import Template

from . import packs
from .records import TEMPLATES
from .util import write_json

LEAD_EXTRA = """
**Lead commands:** `wz decide "<the owner's exact words>" --reading "<your reading>"` (no words: `--proposal`) ·
`wz brief new <slug> --role <role>` · `wz job add <role> "<task>" [-p N] [--after JOB] [--lease R] [--timeout 45m]
[--evidence "..."]` · `wz job hold|release|cancel <id>` · `wz next` (what finished since you last looked) ·
`wz watchdog` · `wz budget` · `wz merge --dry-run` · `wz promote <store>` (asks the owner to sign a release) ·
`wz unlock <role>` · `wz resume <role|all>` · `wz sync` then `wz digest` before the digest time ·
`wz job remint <id>` (a failed or timed-out job, dependents re-pointed) · `wz hold add|list|clear` · `wz prune` ·
`wz backlog refill` · `wz hand list` · `wz bench runs` · `wz ring gate|read <ring>` ·
`wz say <role> "<text>"` · `wz list` (which role sessions are live).

**You delegate; you do not do a role's work.** You plan, write briefs, and hand the work to the role that owns it: to
its live session with `wz say <role> "<one clear task, naming the brief>"`, or as a queued job with `wz job add <role>
"<task>"`. You read their reports and rule on them. If the work belongs to a role, do not open its files and do it
yourself, even when it is small and you could; if no role owns it, say so and propose one. `wz say` types into a live
session and tells you whether the line was sent; a role with no live session gets the line as a note at the top of its
`roles/<role>/STATE.md` (never a job): open its session first (`wz cli <role> --detach`, `wz list` shows when it is at its
input box) or use `wz job add` when work must start. Roles may `wz say` you the same way.

**No timers, no queue.** If this workspace has no timers installed (`wz install timers` was never run; the simple setup
never runs it), `wz job add` starts nothing: no job runs by itself. Open the role's window with `wz cli <role> --detach`,
wait until `wz list` says it is at its input box, then `wz say` it the task. Or ask the person to leave `wz serve --follow`
running in a terminal: it runs the queued jobs in order and says what it holds. Never tell the person a queued job will run
by itself when nothing will serve the queue.

You never write product code and never sign. You rule on every report's asks the day it lands, and you name your own
errors in the digest.
"""

SIMPLE_LEAD = """
**First small task (a check that this works).** The first time the person asks you for something after the setup, hand it
to a helper (`wz cli <helper> --detach`, then `wz say <helper> "<the task, naming the brief>"`), even if it is one
sentence. Then tell them, in plain words, who you gave it to and what they will see when it is done. If you catch yourself
writing the result, stop and hand it over instead.
"""


def simple_marker(cfg) -> Path:
    return cfg.state / "setup" / "simple"


def lead_extra(cfg) -> str:
    """The lead's standing text; a workspace made with `wz init --simple` also gets the first-small-task check."""
    return LEAD_EXTRA + (SIMPLE_LEAD if simple_marker(cfg).is_file() else "")


def hook_settings() -> dict:
    from .worker import wz_argv
    base = " ".join(shlex.quote(a) for a in wz_argv())
    return {"hooks": {
        "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": f"{base} hook guard"}]}],
        "PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": f"{base} hook flag"}]}],
    }}


def _owns_text(r: dict) -> str:
    parts = [f"`{store}`: " + ", ".join(f"`{g}`" for g in globs) for store, globs in r["owns"].items() if globs]
    return "; ".join(parts) or "nothing beyond the shared paths"


MODE_TEXT = {
    "default": "Claude Code asks the owner before it acts. A background job has nobody to answer, so a job cannot do "
               "anything that needs a yes; an interactive session can ask. If a job needs something it cannot get, say "
               "so in your report and stop.",
    "plan": "Claude Code only plans: it does not edit files or run commands. Say in your report what you would have done.",
    "acceptEdits": "Claude Code accepts file edits without asking. It still asks before other actions, and a background "
                   "job cannot be asked: it cannot do anything that needs a yes beyond file edits.",
    "auto": "Claude Code decides for itself what to ask about; it does not ask before every action, and wz has not "
            "checked where it asks. Do not assume you will be stopped: the guard and the owner's review are the limits.",
    "dontAsk": "Claude Code does not ask. wz has not checked what it then allows. Do not assume you will be stopped: the "
               "guard and the owner's review are the limits.",
    "manual": "wz has only checked the `default` mode, not this one. Do not assume where Claude Code asks or does not.",
    "bypassPermissions": "Claude Code does NOT ask before any action, in a chat or a job. Nothing stops you except the "
                         "guard and the owner's review, so check twice before anything you cannot undo.",
}


def mode_note(cfg) -> str:
    mode = cfg.permission_mode()
    return f"**Permission mode: `{mode}`** (`[agent] permission_mode` in wz.toml). " + MODE_TEXT.get(mode, "")


def web_note(cfg, role: str) -> str:
    web = cfg.role(role)["web"]
    if web is True:
        return "Web access: allowed for this role (`web = true`). The guard does not watch what you fetch."
    if web:
        return "Web access: only these tools are allowed for this role: " + ", ".join(f"`{t}`" for t in web) + "."
    return ("Web access: off for this role. The guard refuses WebFetch, WebSearch and MCP tools; do not look for another "
            "way in. If the work needs the web, put the request in your report and stop.")


def render(cfg, role: str) -> str:
    r = cfg.role(role)
    tpl = Template((TEMPLATES / "charter.md").read_text())
    rules = "\n".join(f"- {rule}" for rule, _why in packs.STANDING_RULES)
    pack_rules = "\n".join(f"- {x}" for x in r["rules"]) or "- (none beyond the standing rules)"
    return tpl.substitute(role=role, project=cfg.project, desc=r["desc"], owns=_owns_text(r), rules=rules,
                          pack_rules=pack_rules, lead=cfg.lead(), mode_note=mode_note(cfg), web_note=web_note(cfg, role), lead_extra=lead_extra(cfg) if cfg.is_lead(role) else "")


def agents_md(cfg) -> str:
    lines = [f"# Agents — {cfg.project}", "",
             f"Generated by `wz charters` from wz.toml; edit wz.toml, not this file. Lead: `{cfg.lead()}`.", "",
             "| role | pack | store | owns | model | account | cap |", "|---|---|---|---|---|---|---|"]
    for name, r in cfg.roles().items():
        lines.append(f"| {name} | {r['pack']} | {r['store']} | {_owns_text(r)} | {r['model'] or '(default)'} | "
                     f"{r['account'] or '-'} | {r['cap']} |")
    lines += ["", "Every role may also write its own `roles/<role>/`, the Report section of its brief, new ledger rows, "
              "its scratch dir and the temp dir.", "",
              "## Handoff", "",
              "Work moves by file: the lead writes a brief and queues a job; the role writes its report and a closing "
              "declaration; the flag wakes the lead (`wz next`). Asks for another role go in the report or a ledger row.",
              ""]
    return "\n".join(lines)


def stale(cfg, role: str) -> bool:
    """True when the role's CHARTER.md is missing or no longer carries the mode and web sentences wz.toml now implies (for the
    lead, also the standing lead text of this wz)."""
    p = cfg.charter_path(role)
    if not p.is_file():
        return True
    text = p.read_text()
    if mode_note(cfg) not in text or web_note(cfg, role) not in text:
        return True
    return cfg.is_lead(role) and lead_extra(cfg) not in text


def ensure(cfg, role: str) -> None:
    """Make the role's charter and the hook settings current before a session or job starts; other charters are left alone."""
    if not cfg.role_settings.is_file() or not cfg.charter_path(role).is_file():
        write_all(cfg)
    elif stale(cfg, role):
        cfg.charter_path(role).write_text(render(cfg, role))


def write_all(cfg) -> list[Path]:
    out = []
    for role in cfg.roles():
        d = cfg.role_dir(role)
        d.mkdir(parents=True, exist_ok=True)
        (d / "CHARTER.md").write_text(render(cfg, role))
        out.append(d / "CHARTER.md")
        if not (d / "STATE.md").exists():
            (d / "STATE.md").write_text(f"# {role} — notes for the next job\n\n(nothing yet)\n")
        if not (d / "LESSONS.md").exists():
            (d / "LESSONS.md").write_text(f"# {role} — lessons\n\nOne line each: `- <date> <ref>: what failed -> the rule`.\n")
        if not (d / "BACKLOG.md").exists():
            (d / "BACKLOG.md").write_text(f"# {role} — backlog\n\nThe lead keeps this list; `- [ ]` items are open.\n")
    (cfg.root / "AGENTS.md").write_text(agents_md(cfg))
    out.append(cfg.root / "AGENTS.md")
    write_json(cfg.role_settings, hook_settings())
    out.append(cfg.role_settings)
    return out
