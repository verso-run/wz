"""The wz command line. `wz --help` lists the commands; each has its own --help."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import (__version__, approvals, bench, budget, charters, config, digest, featureflags, flags, guard, hands, jobs,
               leases, merge, records, release, review, worker, scan, setup_mode, timers, unlock, upkeep, watchdog)


def _cfg(args) -> config.Config:
    return config.load(Path(args.config) if getattr(args, "config", None) else None)


def _me() -> str:
    return os.environ.get("WZ_ROLE") or "owner"


def _lead_or_owner(cfg) -> None:
    role = os.environ.get("WZ_ROLE")
    if role and not cfg.is_lead(role):
        raise SystemExit(f"wz: only the lead ({cfg.lead()}) or the owner may do this; you are {role}")


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "(none)"
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    out = ["  ".join(c.ljust(w[c]) for c in cols)]
    out += ["  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols) for r in rows]
    return "\n".join(out)


# ---- commands ------------------------------------------------------------------------------------------------------
def cmd_init(args) -> int:
    d = Path(args.dir or ".").resolve()
    if args.print_charter:
        d.mkdir(parents=True, exist_ok=True)
        print(setup_mode.write_setup_charter(d, simple=args.simple))
        return 0
    if args.example:
        cfg = config.load(d / config.CONFIG_NAME)
        role = args.role or setup_mode.example_role(cfg)
        j = jobs.add(cfg, role, setup_mode.EXAMPLE_TASK, priority=10, timeout="15m", by="setup")
        print(f"queued {j['id']} for {role}; serving it now (foreground)")
        worker.serve(cfg, role=role, wait=True)
        j = jobs.get(cfg, j["id"])
        print(json.dumps({"job": j["id"], "status": j["status"], "result": j.get("result")}, indent=2))
        return 0 if j["status"] == "done" else 1
    if args.answers:
        answers = json.loads(Path(args.answers).read_text())
    elif args.plain or not sys.stdin.isatty() or not shutil.which("claude"):
        if not sys.stdin.isatty():
            raise SystemExit("wz init: no terminal to ask in; pass --answers FILE")
        answers = setup_mode.interview_plain()
    else:
        return setup_mode.launch_setup(d, simple=args.simple)
    cfg = setup_mode.apply(answers, d, force=args.force, git_init=not args.no_git, simple=args.simple)
    print(f"wrote {cfg.path}, the workspace files, {len(cfg.roles())} charters and the hook settings")
    if args.simple:
        print("next: `wz cli mission-ctl` to talk to wz. Nothing runs by itself: no timers are installed.")
    else:
        print("next: `wz sign set-pin` (your own terminal), `wz install timers --dry-run`, `wz init --example`")
    return 0


def cmd_cli(args) -> int:
    path = config.find(Path(args.dir).resolve() if args.dir else None) if not args.config else Path(args.config)
    if not path:
        if args.role in ("mission-ctl", None):
            print("no wz.toml here: starting mission-ctl in setup mode")
            return setup_mode.launch_setup(Path(args.dir or ".").resolve())
        raise SystemExit("wz: no wz.toml here or above; run `wz init` first")
    cfg = config.load(path)
    role = args.role or cfg.lead()
    r = cfg.role(role)
    if not cfg.charter_path(role).is_file() or not cfg.role_settings.is_file():
        charters.write_all(cfg)
    a = cfg.agent()
    cmd = [*a["command"].split(), "--append-system-prompt-file", str(cfg.charter_path(role)),
           "--settings", str(cfg.role_settings), "--permission-mode", a["permission_mode"]]
    if r["model"]:
        cmd += ["--model", r["model"]]
    if a.get("pass_effort") and r["effort"]:
        cmd += ["--effort", r["effort"]]
    cwd = cfg.store_root(r["store"])
    env = {"WZ_ROLE": role, "WZ_CONFIG": str(cfg.path), "WZ_HOME": str(cfg.root), "WZ_SCRATCH": str(cfg.scratch(role))}
    acct = cfg.account(r["account"]).get("config_dir") if r["account"] else ""
    if acct:
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(acct)
    cfg.scratch(role).mkdir(parents=True, exist_ok=True)
    if args.print:
        print("cd " + str(cwd))
        print(" ".join(f"{k}={v}" for k, v in env.items()) + " " + " ".join(cmd))
        return 0
    if args.no_tmux or not shutil.which("tmux"):
        return subprocess.call(cmd, cwd=str(cwd), env={**os.environ, **env})
    name = f"wz-{timers._slug(cfg)}-{role}"
    if subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode != 0:
        t = ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd)]
        for k, v in env.items():
            t += ["-e", f"{k}={v}"]
        subprocess.run(t + cmd, check=True)
    if args.detach:
        print(f"started {name}; attach with: tmux attach -t {name}")
        return 0
    return subprocess.call(["tmux", "attach", "-t", name])


def cmd_charters(args) -> int:
    cfg = _cfg(args)
    for p in charters.write_all(cfg):
        print(f"wrote {p}")
    return 0


def cmd_job(args) -> int:
    cfg = _cfg(args)
    if args.action == "add":
        j = jobs.add(cfg, args.role, args.task, priority=args.priority, after=args.after, timeout=args.timeout,
                     lease=args.lease or [], unlock=not args.no_unlock, brief=args.brief, evidence=args.evidence,
                     worktree=not args.no_worktree, by=_me())
        print(f"{j['id']} queued for {j['role']} (P{j['priority']}" + (f", after {j['after']}" if j["after"] else "") + ")")
        return 0
    if args.action in ("list", None):
        every = jobs.all_jobs(cfg, args.role)
        if not args.all:
            every = [j for j in every if j["status"] in ("queued", "held", "running")]
        by_id = {j["id"]: j for j in jobs.all_jobs(cfg)}
        rows = []
        for j in jobs.queue_order(every):
            note = jobs.wait_reason(cfg, j, by_id) if j["status"] == "queued" else (j.get("result") or {}).get("result", "")
            rows.append({"id": j["id"], "role": j["role"], "P": j["priority"], "status": j["status"],
                         "task": j["task"][:50], "note": (note or "")[:60]})
        print(_table(rows, ["id", "role", "P", "status", "task", "note"]))
        return 0
    j_id = args.id
    if args.action == "show":
        print(json.dumps(jobs.get(cfg, j_id), indent=2))
        return 0
    _lead_or_owner(cfg)
    if args.action == "remint":
        j = jobs.remint(cfg, j_id, timeout=args.timeout, by=_me())
        print(f"{j['id']} reminted from {j_id}" + (f"; re-pointed {', '.join(j['repointed'])}" if j["repointed"] else ""))
        return 0
    fn = {"cancel": jobs.cancel, "hold": jobs.hold, "release": jobs.release}[args.action]
    j = fn(cfg, j_id) if args.action == "release" else fn(cfg, j_id, args.why or "")
    print(f"{j['id']} is {j['status']}")
    return 0


def cmd_serve(args) -> int:
    cfg = _cfg(args)
    say = (lambda *_: None) if args.quiet else print
    worker.serve(cfg, role=args.role, wait=args.wait, dry_run=args.dry_run, say=say)
    return 0


def cmd_run(args) -> int:
    cfg = _cfg(args)
    j = worker.run_job(cfg, args.id)
    print(f"{j['id']}: {j['status']}")
    return 0


def cmd_merge(args) -> int:
    cfg = _cfg(args)
    say = (lambda *_: None) if args.quiet else print
    merge.merge(cfg, store=args.store, dry_run=args.dry_run, say=say)
    return 0


def cmd_promote(args) -> int:
    cfg = _cfg(args)
    _lead_or_owner(cfg)
    r = merge.promote(cfg, args.store, by=_me())
    print(f"{r['id']}: {r['what']} — waits for the owner's sign")
    return 0


def cmd_budget(args) -> int:
    cfg = _cfg(args)
    print(_table(budget.table(cfg), ["account", "spent", "cap"]))
    return 0


def cmd_watchdog(args) -> int:
    cfg = _cfg(args)
    alerts = watchdog.check(cfg)
    if args.json:
        print(json.dumps(alerts, indent=2))
    elif not args.quiet:
        for a in alerts:
            print(f"{a['kind']:9} {a['ref']:10} {a['text']}")
        if not alerts:
            print("no alerts")
    return 0


def cmd_next(args) -> int:
    cfg = _cfg(args)
    evs = flags.since_cursor(cfg, peek=args.peek)
    for e in evs:
        print(f"{e['at']}  {e['role']:12} {e['kind']:12} {e['ref']:10} {e['text']}")
        if e["kind"] == "job":
            try:
                r = jobs.get(cfg, e["ref"]).get("result") or {}
            except jobs.JobError:
                continue
            for k in ("owner_asks", "lead_asks"):
                for a in r.get(k) or []:
                    print(f"{'':14}{k[:-1].replace('_', ' ')}: {a}")
    if not evs:
        print("nothing new")
    return 0


def cmd_wait(args) -> int:
    cfg = _cfg(args)
    ok = flags.wait(cfg, args.role, args.file, timeout_s=args.timeout)
    print("flag raised" if ok else "timed out")
    return 0 if ok else 1


def cmd_decide(args) -> int:
    cfg = _cfg(args)
    _lead_or_owner(cfg)
    did = records.decide(cfg, None if args.proposal else args.words, args.reading or "", proposal=args.proposal)
    print(f"{did} recorded" + (" as a proposal (no owner's words)" if args.proposal or not args.words else ""))
    return 0


def cmd_ledger(args) -> int:
    cfg = _cfg(args)
    fields = dict(kv.split("=", 1) for kv in args.field or [])
    if args.text:
        key = {"defects": "what", "followups": "task", "hypotheses": "hypothesis"}[args.ledger]
        fields.setdefault(key, args.text)
    fields.setdefault("role", os.environ.get("WZ_ROLE", ""))
    print(records.ledger_add(cfg, args.ledger, fields))
    return 0


def cmd_brief(args) -> int:
    cfg = _cfg(args)
    _lead_or_owner(cfg)
    print(records.brief_new(cfg, args.slug, args.role, args.title or ""))
    return 0


def cmd_sync(args) -> int:
    print(digest.sync(_cfg(args), args.date))
    return 0


def cmd_digest(args) -> int:
    cfg = _cfg(args)
    p = digest.write(cfg, args.date)
    print(p)
    return 0


def cmd_sign(args) -> int:
    cfg = _cfg(args)
    try:
        if args.action == "request":
            r = approvals.request(cfg, args.what, command=args.cmd, why=args.why or "", ring=args.ring, by=_me())
            print(f"{r['id']} waits for the owner's sign")
        elif args.action == "list":
            rows = [{"id": r["id"], "status": r["status"], "by": r.get("by", ""), "what": r["what"][:70]}
                    for r in approvals.all_requests(cfg) if args.all or r["status"] in ("pending", "signed")]
            print(_table(rows, ["id", "status", "by", "what"]))
        elif args.action == "set-pin":
            approvals.owner_only()
            a, b = getpass.getpass("new PIN: "), getpass.getpass("again: ")
            if a != b:
                raise approvals.SignError("the two PINs differ")
            approvals.set_pin(cfg, a)
            print("PIN set")
        elif args.action in ("approve", "deny"):
            approvals.owner_only()
            r = approvals.get(cfg, args.id)
            print(f"{r['id']}: {r['what']}\nwill run: {r.get('command') or json.dumps(r.get('action'))}")
            pin = getpass.getpass("PIN: ")
            if args.action == "approve":
                approvals.sign(cfg, args.id, pin)
                print(f"signed {args.id}; it runs with `wz sign run {args.id}`")
            else:
                approvals.deny(cfg, args.id, pin, why=args.why or "")
                print(f"denied {args.id}")
        elif args.action == "run":
            r = approvals.run(cfg, args.id)
            print(r.get("output", ""))
            return 0 if r.get("rc") == 0 else 1
    except approvals.SignError as e:
        raise SystemExit(f"wz sign: {e}")
    return 0


def cmd_approve(args) -> int:
    cfg = _cfg(args)
    approvals.owner_only()
    if not approvals.has_pin(cfg):
        raise SystemExit("set a PIN first: wz sign set-pin")
    from . import approve_page
    srv = approve_page.server(cfg, args.host, args.port)
    print(f"approval page on http://{args.host}:{srv.server_address[1]}/ (Ctrl-C stops it)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_lease(args) -> int:
    cfg = _cfg(args)
    if args.action == "list":
        print(_table(leases.table(cfg), ["resource", "kind", "free", "holder", "since", "expires"]))
        return 0
    argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
    if not argv:
        raise SystemExit("wz lease run <resource> -- <command ...>")
    try:
        return leases.run_with(cfg, [args.resource], argv, holder=os.environ.get("WZ_JOB") or _me(), wait_s=args.wait)
    except leases.LeaseError as e:
        raise SystemExit(f"wz lease: {e}")


def cmd_halt(args) -> int:
    cfg = _cfg(args)
    lane = args.lane
    if lane != "all":
        cfg.role(lane)
    worker.halt(cfg, lane, args.why or "", by=_me())
    print(f"{lane} halted; only the lead lifts it (wz resume {lane})")
    return 0


def cmd_resume(args) -> int:
    cfg = _cfg(args)
    _lead_or_owner(cfg)
    print(f"{args.lane} resumed" if worker.resume(cfg, args.lane) else f"{args.lane} was not halted")
    return 0


def cmd_unlock(args) -> int:
    cfg = _cfg(args)
    _lead_or_owner(cfg)
    cfg.role(args.role)
    if args.revoke:
        unlock.revoke(cfg, args.role)
        print(f"{args.role} locked")
    else:
        unlock.grant(cfg, args.role, hours=args.hours, by=_me())
        print(f"{args.role} may commit for {args.hours} h")
    return 0


def cmd_hook(args) -> int:
    if args.which == "guard":
        return guard.main()
    return flags.hook()


def cmd_install(args) -> int:
    cfg = _cfg(args)
    if args.what == "hooks":
        charters.write_all(cfg)
        print(f"wrote {cfg.role_settings}")
        return 0
    home = Path(args.root).resolve() if args.root else None
    if args.uninstall:
        timers.uninstall(cfg, args.platform, home, dry_run=args.dry_run)
    else:
        timers.install(cfg, args.platform, home, dry_run=args.dry_run)
    return 0


def cmd_scan(args) -> int:
    pub = {}
    path = Path(args.config) if args.config else config.find()
    if path:
        try:
            pub = config.load(path).section("publish")
        except config.ConfigError:
            pub = {}
    pats = scan.load_patterns(Path(args.deny_file) if args.deny_file else None, pub.get("deny", []))
    if args.emails:
        pats.append(scan.EMAIL)
    if not pats:
        raise SystemExit("wz scan: no patterns (use [publish] deny in wz.toml, --deny-file or --emails)")
    hits = scan.scan(Path(args.path), pats, allow=pub.get("allow", []) + (args.allow or []))
    for rel, n, pat, line in hits:
        print(f"{rel}:{n}: [{pat}] {line}")
    print(f"{len(hits)} hit(s) in {Path(args.path).resolve().name}")
    return 1 if hits else 0


def cmd_status(args) -> int:
    cfg = _cfg(args)
    if args.html:
        from . import dashboard
        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(dashboard.render(cfg))
        print(out)
        return 0
    every = jobs.all_jobs(cfg)
    rows = []
    for role, r in cfg.roles().items():
        mine = [j for j in every if j["role"] == role]
        rows.append({"role": role, "pack": r["pack"], "running": sum(j["status"] == "running" for j in mine),
                     "queued": sum(j["status"] == "queued" for j in mine), "held": sum(j["status"] == "held" for j in mine),
                     "halted": "yes" if worker.halted(cfg, role) else "", "unlock": "yes" if unlock.has(cfg, role) else ""})
    print(f"{cfg.project} — lead {cfg.lead()} — {cfg.root}")
    print(_table(rows, ["role", "pack", "running", "queued", "held", "halted", "unlock"]))
    alerts = watchdog.check(cfg, apply=False)
    print(f"\n{len(alerts)} alert(s); {len(approvals.pending(cfg))} sign(s) pending; {len(hands.waiting(cfg))} hand-step(s) "
          f"waiting; {len(release.open_holds(cfg))} open hold(s); spent today {budget.spent(cfg):.2f} USD")
    return 0


def _kv(items) -> dict:
    out = {}
    for kv in items or []:
        if "=" not in kv:
            raise SystemExit(f"wz: expected name=value, got {kv!r}")
        k, v = kv.split("=", 1)
        out[k] = v
    return out


def cmd_hand(args) -> int:
    cfg = _cfg(args)
    try:
        if args.action == "ask":
            h = hands.ask(cfg, args.text, by=_me(), resource=args.resource, why=args.why or "", timeout=args.timeout)
            print(f"{h['id']} waits for a person: hands/{h['id']}.md")
        elif args.action == "wait":
            h = hands.wait(cfg, args.id, timeout_s=args.timeout or None)
            print(f"{h['id']}: {h['status']}" + (f" ({h.get('note')})" if h.get("note") else ""))
            return 0 if h["status"] == "done" else 1
        elif args.action in ("done", "refuse"):
            h = hands.answer(cfg, args.id, "done" if args.action == "done" else "refused", args.who or getpass.getuser(),
                             args.note or "")
            print(f"{h['id']}: {h['status']}")
        elif args.action == "attend":
            r = hands.attend(cfg, args.who or getpass.getuser(), args.minutes)
            print(f"{r['who']} at the bench until {r['until']}")
        elif args.action == "leave":
            hands.leave(cfg)
            print("left the bench; hazardous steps now refuse")
        else:
            rows = [{"id": h["id"], "status": h["status"], "by": h["by"], "resource": h.get("resource") or "",
                     "hazard": "yes" if h["hazard"] else "", "what": h["text"][:60]}
                    for h in (hands.all_steps(cfg) if args.all else hands.waiting(cfg))]
            print(_table(rows, ["id", "status", "by", "resource", "hazard", "what"]))
            a = hands.attended(cfg)
            print(f"attended by {a['who']} until {a['until']}" if a else "nobody attending")
    except hands.HandError as e:
        raise SystemExit(f"wz hand: {e}")
    return 0


def cmd_bench(args) -> int:
    cfg = _cfg(args)
    try:
        if args.action == "run":
            r = bench.run(cfg, Path(args.scenario), cwd=Path(args.cwd) if args.cwd else None)
            print(f"{r['run']}: {r['verdict']}" + (f" ({r['why']})" if r.get("why") else ""))
            print(bench.runs_dir(cfg) / r["run"] / "REPORT.md")
            return 0 if r["verdict"] == "pass" else 1
        if args.action == "gate":
            text = Path(args.size_file).read_text() if args.size_file else subprocess.run(
                args.size_cmd, shell=True, capture_output=True, text=True, check=True).stdout
            g = bench.budget_gate(bench.parse_size(text), bench.budget_limits(cfg, args.target))
            for k, c in g["checks"].items():
                print(f"{k:5} {c['used']} of {c['limit']} B ({c['pct']} %), headroom {c['headroom']}: {'pass' if c['pass'] else 'OVER'}")
            return 0 if g["pass"] else 1
        if args.action == "parity":
            rec = int(args.record) if args.record.isdigit() else args.record
            p = bench.parity(Path(args.device).read_bytes(), Path(args.host).read_bytes(), rec)
            print(json.dumps(p, indent=2))
            return 0 if p["equal"] else 1
        if args.action == "capture":
            reuse = leases.inherited(cfg, [args.instrument])
            fds = [] if reuse else leases.acquire(cfg, [args.instrument], os.environ.get("WZ_JOB") or _me(), hold_s=300)
            if fds is None:
                raise SystemExit(f"wz bench: {args.instrument} is leased by someone else")
            try:
                hands.require_attended(cfg, [args.instrument], "capture")
                print(json.dumps(bench.capture(cfg, args.instrument, _kv(args.read)), indent=2))
            finally:
                leases.release(cfg, [] if reuse else [args.instrument], fds)
            return 0
        if args.action == "ready":
            r = bench.ready_for_owner(cfg, Path(args.scenario), args.commit)
            print(f"ready: agent run {r['run']} passed at {r['commit'][:12]}; hand over with {bench.runs_dir(cfg) / r['run'] / 'REPORT.md'}")
            return 0
        rows = [{"run": r["run"], "verdict": r["verdict"], "commit": r["commit"][:12], "by": r["by"],
                 "finished": r.get("finished", "")} for r in bench.all_runs(cfg)]
        print(_table(rows, ["run", "verdict", "commit", "by", "finished"]))
    except (bench.BenchError, hands.HandError) as e:
        raise SystemExit(f"wz bench: {e}")
    return 0


def cmd_hold(args) -> int:
    cfg = _cfg(args)
    try:
        if args.action == "add":
            h = release.hold_add(cfg, args.ref, args.level, args.text, evidence=args.evidence or "", expires=args.expires,
                                 by=_me())
            print(f"{h['id']} {h['level']} on {h['ref']} until {h['expires']}")
        elif args.action == "clear":
            _lead_or_owner(cfg)
            h = release.hold_clear(cfg, args.id, args.decision, by=_me())
            print(f"{h['id']} cleared by {h['decision']}")
        else:
            rows = [{"id": h["id"], "state": h["state"], "level": h["level"], "ref": h["ref"], "expires": h["expires"],
                     "text": h["text"][:60]} for h in release.holds(cfg) if args.all or h["state"] == "open"]
            print(_table(rows, ["id", "state", "level", "ref", "expires", "text"]))
    except release.ReleaseError as e:
        raise SystemExit(f"wz hold: {e}")
    return 0


def cmd_ring(args) -> int:
    cfg = _cfg(args)
    try:
        if args.action == "pin":
            r = release.pin(cfg, args.ring, Path(args.artifact), _kv(args.param), by=_me())
            print(f"{args.ring} pinned to {Path(r['artifact']).name} sha256 {r['sha256'][:16]}")
        elif args.action == "gate":
            r = release.gate(cfg, args.ring, Path(args.artifact) if args.artifact else None)
            for g in r["gates"]:
                print(f"rc={g['rc']}  {g['gate']}")
            print(f"{args.ring} gate {'pass' if r['pass'] else 'FAIL'} for {r['sha256'][:12]}: {r['evidence']}")
            return 0 if r["pass"] else 1
        elif args.action == "rehearse":
            r = release.rehearse(cfg, args.ring)
            print(" -> ".join(f"{s['step']} rc={s['rc']}" for s in r["steps"]) + (": pass" if r["pass"] else ": FAIL"))
            return 0 if r["pass"] else 1
        elif args.action == "read":
            r = release.live_read(cfg, args.ring, args.field)
            print(f"{r['ring']} {r['field']} = {json.dumps(r['value'])} (read {r['read_at']} from {r['url']})")
    except release.ReleaseError as e:
        raise SystemExit(f"wz ring: {e}")
    return 0


def cmd_flags(args) -> int:
    cfg = _cfg(args)
    errors, warnings = featureflags.check(cfg)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    print(f"{len(featureflags.load_registry(cfg))} flag(s) registered, {len(errors)} error(s)")
    return 1 if errors else 0


def cmd_backlog(args) -> int:
    cfg = _cfg(args)
    added = upkeep.refill(cfg, dry_run=args.dry_run)
    for role, ids in added.items():
        print(f"{role}: {'would add' if args.dry_run else 'added'} {', '.join(ids)}")
    if not added:
        print("nothing new")
    return 0


def cmd_prune(args) -> int:
    cfg = _cfg(args)
    if args.apply:
        _lead_or_owner(cfg)
    acts = upkeep.prune(cfg, apply=args.apply)
    for a in acts:
        print(f"{'' if args.apply else 'would '}{a['action']} {a['job']}: {a['why']}")
    if not acts:
        print("nothing to prune")
    return 0


def cmd_nightly(args) -> int:
    made = upkeep.nightly(_cfg(args))
    print(f"queued {', '.join(made)}" if made else "nothing to queue (already queued today, or no [[nightly]] entries)")
    return 0


def cmd_review(args) -> int:
    cfg = _cfg(args)
    try:
        if args.action == "collect":
            print(review.collect(cfg, Path(args.session), args.name, by=_me()))
        elif args.action == "words":
            print(review.words(cfg, args.name, args.text))
        else:
            ds = review.drafts(cfg)
            for n in ds:
                print(f"{n}: waiting for the owner's words")
            if not ds:
                print("no drafts waiting")
    except review.ReviewError as e:
        raise SystemExit(f"wz review: {e}")
    return 0


# ---- parser --------------------------------------------------------------------------------------------------------
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wz", description="Mission control for a team of AI agents: a lead, owned work, "
                                "a job queue, a guard, and the owner's sign.")
    p.add_argument("--version", action="version", version=f"wz {__version__}")
    p.add_argument("--config", help="path to wz.toml (default: $WZ_CONFIG, else the nearest one above)")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    def add(name, fn, help_=None):
        sp = sub.add_parser(name, help=help_, description=help_) if help_ else sub.add_parser(name)
        sp.set_defaults(fn=fn)
        return sp

    s = add("init", cmd_init, "set up a project (interview by the lead, or --plain / --answers); --example runs the first job")
    s.add_argument("--dir")
    s.add_argument("--answers")
    s.add_argument("--plain", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-git", action="store_true")
    s.add_argument("--example", action="store_true")
    s.add_argument("--role")
    s.add_argument("--simple", action="store_true",
                   help="plain-words setup that starts safe: Claude Code keeps asking, you choose a daily spend cap, no timers")
    s.add_argument("--print-charter", action="store_true",
                   help="write the setup instructions to .wz/setup/CHARTER.md and print its path (for a Claude session that is already open)")

    s = add("cli", cmd_cli, "start a role's interactive session in tmux (no config + mission-ctl = setup mode)")
    s.add_argument("role", nargs="?")
    s.add_argument("--dir")
    s.add_argument("--detach", action="store_true")
    s.add_argument("--no-tmux", action="store_true")
    s.add_argument("--print", action="store_true", help="print the command instead of running it")

    add("charters", cmd_charters, "regenerate charters, AGENTS.md and the hook settings from wz.toml")

    s = add("job", cmd_job, "add, list, show, hold, release or cancel jobs")
    js = s.add_subparsers(dest="action")
    a = js.add_parser("add")
    a.add_argument("role")
    a.add_argument("task")
    a.add_argument("-p", "--priority", type=int, default=50, help="lower runs first (default 50)")
    a.add_argument("--after", help="job id this one waits for")
    a.add_argument("--timeout")
    a.add_argument("--lease", action="append", help="resource to lease for the whole job (repeatable)")
    a.add_argument("--no-unlock", action="store_true", help="the job may not commit")
    a.add_argument("--brief")
    a.add_argument("--evidence", help="what done will be checked against")
    a.add_argument("--no-worktree", action="store_true")
    a = js.add_parser("list")
    a.add_argument("--role")
    a.add_argument("--all", action="store_true")
    for name in ("show", "cancel", "hold", "release"):
        a = js.add_parser(name)
        a.add_argument("id")
        if name in ("cancel", "hold"):
            a.add_argument("--why")
    a = js.add_parser("remint", help="re-queue a failed, blocked or cancelled job; dependents follow the new id")
    a.add_argument("id")
    a.add_argument("--timeout", help="default: the old timeout, doubled when it timed out")
    s.set_defaults(role=None, all=False)

    s = add("queue", cmd_job, "the queue (same as `wz job list`)")
    s.set_defaults(action="list", role=None, all=False)
    s.add_argument("--all", action="store_true")
    s.add_argument("--role")

    s = add("serve", cmd_serve, "start ready jobs (the serve timer runs this every minute)")
    s.add_argument("--role")
    s.add_argument("--wait", action="store_true", help="run each started job in the foreground")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--quiet", action="store_true")

    s = add("_run", cmd_run)
    s.add_argument("id")

    s = add("merge", cmd_merge, "integrate finished job branches (the merge timer runs this)")
    s.add_argument("--store")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--quiet", action="store_true")

    s = add("promote", cmd_promote, "ask the owner to sign moving main to the integration tip")
    s.add_argument("store")

    add("budget", cmd_budget, "spend today per account against its cap")

    s = add("watchdog", cmd_watchdog, "lost, overdue, stuck, orphaned and idle work; unsigned requests")
    s.add_argument("--json", action="store_true")
    s.add_argument("--quiet", action="store_true")

    s = add("next", cmd_next, "what happened since the lead last looked")
    s.add_argument("--peek", action="store_true", help="do not move the cursor")

    s = add("wait", cmd_wait, "block this shell until a role writes a brief or ledger file")
    s.add_argument("role")
    s.add_argument("file")
    s.add_argument("--timeout", type=float, default=0)

    s = add("decide", cmd_decide, "record a decision in the owner's exact words")
    s.add_argument("words", nargs="?")
    s.add_argument("--reading", help="the lead's reading of it")
    s.add_argument("--proposal", action="store_true", help="no owner's words: record a proposal")

    s = add("ledger", cmd_ledger, "append a row to a ledger")
    s.add_argument("verb", choices=["add"])
    s.add_argument("ledger", choices=list(records.LEDGERS))
    s.add_argument("text", nargs="?")
    s.add_argument("--field", action="append", help="column=value (repeatable)")

    s = add("brief", cmd_brief, "write a new numbered brief from the template")
    s.add_argument("verb", choices=["new"])
    s.add_argument("slug")
    s.add_argument("--role", required=True)
    s.add_argument("--title")

    s = add("sync", cmd_sync, "create today's sync file for the lead")
    s.add_argument("--date")
    s = add("digest", cmd_digest, "compose the owner's digest")
    s.add_argument("--date")

    s = add("sign", cmd_sign, "ask for, give, refuse or run the owner's sign")
    ss = s.add_subparsers(dest="action", required=True)
    a = ss.add_parser("request")
    a.add_argument("what")
    a.add_argument("--cmd", required=True, help="the exact command that runs once signed")
    a.add_argument("--why")
    a.add_argument("--ring")
    a = ss.add_parser("list")
    a.add_argument("--all", action="store_true")
    ss.add_parser("set-pin")
    for name in ("approve", "deny", "run"):
        a = ss.add_parser(name)
        a.add_argument("id")
        if name == "deny":
            a.add_argument("--why")

    s = add("approve", cmd_approve, "serve the approval page (owner only)")
    s.add_argument("verb", choices=["serve"])
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)

    s = add("lease", cmd_lease, "list resource leases, or hold one for a command")
    ls = s.add_subparsers(dest="action", required=True)
    ls.add_parser("list")
    a = ls.add_parser("run")
    a.add_argument("resource")
    a.add_argument("--wait", type=float, default=0, help="seconds to wait for the lease (default: do not wait)")
    a.add_argument("argv", nargs=argparse.REMAINDER)

    s = add("halt", cmd_halt, "stop a lane at once (the andon cord); only the lead lifts it")
    s.add_argument("lane", help="a role, or all")
    s.add_argument("--why")
    s = add("resume", cmd_resume, "lift a halt (lead)")
    s.add_argument("lane")

    s = add("unlock", cmd_unlock, "let a chat session commit for a while (lead)")
    s.add_argument("role")
    s.add_argument("--hours", type=float, default=2)
    s.add_argument("--revoke", action="store_true")

    s = add("hook", cmd_hook, "Claude Code hook entry points (guard, flag)")
    s.add_argument("which", choices=["guard", "flag"])

    s = add("install", cmd_install, "write the hook settings, or install the timers")
    s.add_argument("what", choices=["hooks", "timers"])
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--root", help="write unit files under this directory instead of your home (for a dry run)")
    s.add_argument("--platform", choices=["linux", "macos"])
    s.add_argument("--uninstall", action="store_true")

    s = add("scan", cmd_scan, "leak scan a tree before publishing it")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("--deny-file")
    s.add_argument("--allow", action="append")
    s.add_argument("--emails", action="store_true", help="also flag every email address")

    s = add("status", cmd_status, "one screen: roles, queue, alerts, signs, hand-steps, holds, spend")
    s.add_argument("--html", help="write the status dashboard (static HTML) to this file instead")

    s = add("hand", cmd_hand, "hand-steps: physical actions only a person does; attendance for hazardous hardware")
    hs = s.add_subparsers(dest="action")
    a = hs.add_parser("ask")
    a.add_argument("text")
    a.add_argument("--resource")
    a.add_argument("--why")
    a.add_argument("--timeout", default="2h")
    a = hs.add_parser("wait")
    a.add_argument("id")
    a.add_argument("--timeout", type=float, default=0)
    for name in ("done", "refuse"):
        a = hs.add_parser(name)
        a.add_argument("id")
        a.add_argument("--note")
        a.add_argument("--who")
    a = hs.add_parser("attend", help="a person declares they are at the bench (hazardous steps need it)")
    a.add_argument("--minutes", type=float, default=60)
    a.add_argument("--who")
    hs.add_parser("leave")
    a = hs.add_parser("list")
    a.add_argument("--all", action="store_true")
    s.set_defaults(action="list", all=False)

    s = add("bench", cmd_bench, "the bench loop: run a scenario, budget gate, parity, instrument capture, owner hand-over")
    bs = s.add_subparsers(dest="action")
    a = bs.add_parser("run")
    a.add_argument("scenario")
    a.add_argument("--cwd", help="where the scenario's commands run (default: the scenario's directory)")
    a = bs.add_parser("gate", help="flash and RAM against [bench.budget.<target>]")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--size-file")
    g.add_argument("--size-cmd")
    a.add_argument("--target", default="default")
    a = bs.add_parser("parity", help="device records vs the host reference, byte for byte")
    a.add_argument("device")
    a.add_argument("host")
    a.add_argument("--record", default="line", help="line, or a fixed record size in bytes")
    a = bs.add_parser("capture", help="read an instrument over SCPI: field=QUERY ...")
    a.add_argument("instrument")
    a.add_argument("read", nargs="+")
    a = bs.add_parser("ready", help="the agent's passing run of this scenario at this commit, or refuse")
    a.add_argument("scenario")
    a.add_argument("--commit")
    bs.add_parser("runs")
    s.set_defaults(action="runs")

    s = add("hold", cmd_hold, "holds with an expiry: BLOCKS, INCONCLUSIVE, NOTE, FREEZE (a presign window)")
    hs = s.add_subparsers(dest="action")
    a = hs.add_parser("add")
    a.add_argument("ref", help="a store, ring, commit or job")
    a.add_argument("text")
    a.add_argument("--level", default="BLOCKS", type=str.upper, choices=list(release.LEVELS))
    a.add_argument("--evidence")
    a.add_argument("--expires", default="7d")
    a = hs.add_parser("clear")
    a.add_argument("id")
    a.add_argument("--decision", required=True, help="the DECISIONS.md row that clears it")
    a = hs.add_parser("list")
    a.add_argument("--all", action="store_true")
    s.set_defaults(action="list", all=False)

    s = add("ring", cmd_ring, "rings: pin an artifact by hash, run its gates, rehearse the rollback, read the live ring")
    rs = s.add_subparsers(dest="action", required=True)
    a = rs.add_parser("pin")
    a.add_argument("ring")
    a.add_argument("artifact")
    a.add_argument("--param", action="append", help="name=value, declared in [release] pin_params")
    a = rs.add_parser("gate")
    a.add_argument("ring")
    a.add_argument("--artifact")
    a = rs.add_parser("rehearse")
    a.add_argument("ring")
    a = rs.add_parser("read")
    a.add_argument("ring")
    a.add_argument("field", help="dotted path into the ring's health JSON")

    s = add("flags", cmd_flags, "feature flag inventory check (CI): registered, owned, off by default")
    s.add_argument("verb", choices=["check"])

    s = add("backlog", cmd_backlog, "refill role backlogs from open ledger rows")
    s.add_argument("verb", choices=["refill"])
    s.add_argument("--dry-run", action="store_true")

    s = add("prune", cmd_prune, "duplicates, stale holds and off-focus jobs (report; --apply acts)")
    s.add_argument("--apply", action="store_true")

    add("nightly", cmd_nightly, "queue the [[nightly]] jobs once per day (the nightly timer runs this)")

    s = add("review", cmd_review, "post-run review: collect a session, pack metrics, draft; the owner adds their words")
    rv = s.add_subparsers(dest="action")
    a = rv.add_parser("collect")
    a.add_argument("session")
    a.add_argument("--name")
    a = rv.add_parser("words")
    a.add_argument("name")
    a.add_argument("text")
    rv.add_parser("list")
    s.set_defaults(action="list")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.config:
        os.environ["WZ_CONFIG"] = str(Path(args.config).resolve())
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    try:
        return int(args.fn(args) or 0)
    except (config.ConfigError, jobs.JobError, leases.LeaseError, setup_mode.SetupError, bench.BenchError,
            release.ReleaseError, ValueError) as e:
        print(f"wz: {e}", file=sys.stderr)
        return 1
