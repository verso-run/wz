"""The bench loop: hardware : firmware : software : app : instrument, one scenario at a time.

A scenario (a TOML file, usually bench/scenarios/<name>.toml) names the device under test, the instruments, an
optional test phone, and an ordered list of steps. `wz bench run <scenario>` runs them under one set of leases and
writes every result as an evidence file in a run directory, then a report that names each field it read.

Step kinds:
  host      host build and tests                        run = "<command>"
  firmware  firmware build, then the flash/RAM gate      run = "<build>", size = "<size command>" | size_file, budget = "<target>"
  flash     put the image on the leased device           run = "<command>"
  drive     play recorded or generated inputs into it    run = "<command>" (replay tool, signal generator script)
  capture   read instruments over SCPI (TCP)             instrument = "<resource>", read = { field = "<query>" }, limits = {}
  records   pull the device's own records                run = "<command>", out = "<file in the run dir>"
  parity    host reference replays the device's inputs   run = "<host replay command>", device = "<file>", host = "<file>",
            and must match the device byte for byte      record = "line" | <bytes per record>
  app       the app on the leased test phone, same scenario, end to end      run = "<command>"
  hand      a physical action by a person; waits         text = "...", resource = "<name>", timeout = "30m"

Scenario keys: name, device, phone, instruments, cwd (where commands run, relative to the scenario file), timeout
(the lease bound), safe_state (the command that makes the bench safe when a limit is crossed), [[step]].
In commands, {run} is the run directory, {commit} the source commit, {device}/{phone} the resource names and
{device.<key>} / {phone.<key>} / {<instrument>.<key>} any field of those resources in wz.toml.

Device rules (wz.toml [resources.*]): `protected = true` is never leased or driven; `pair_only_with = "<phone>"` means
the device's pairing slot belongs to that phone, so a scenario that pairs it with any other phone is refused;
`hazard = true` makes every step on it attended only (hands.py). The owner is never the first tester: `wz bench ready`
names an agent's passing run of the same scenario at the same commit, or refuses.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import tomllib
from pathlib import Path

from . import flags, hands, leases, worker
from .util import iso, now, parse_duration, read_json, write_json

KINDS = ("host", "firmware", "flash", "drive", "capture", "records", "parity", "app", "hand")
DEVICE_KINDS = {"flash", "drive", "capture", "records", "app"}


class BenchError(Exception):
    pass


# ---- the flash and RAM budget gate ---------------------------------------------------------------------------------
_UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024, "kib": 1024, "m": 1024 * 1024, "mb": 1024 * 1024, "mib": 1024 * 1024}


def parse_bytes(v) -> int:
    if isinstance(v, int):
        return v
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$", str(v))
    if not m or m.group(2).lower() not in _UNITS:
        raise BenchError(f"not a size: {v!r} (use 524288, 512K or 1M)")
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def parse_size(text: str) -> dict:
    """Image sizes from a `size` tool's Berkeley output (text data bss ...), or a JSON object {"flash": n, "ram": n}.

    Flash is text + data (data's initial values live in flash); RAM is data + bss."""
    text = text.strip()
    if text.startswith("{"):
        d = json.loads(text)
        return {"flash": int(d["flash"]), "ram": int(d["ram"]), "source": "json"}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) >= 3 and all(c.isdigit() for c in cols[:3]):
            t, d, b = (int(c) for c in cols[:3])
            return {"flash": t + d, "ram": d + b, "text": t, "data": d, "bss": b, "source": "berkeley"}
    raise BenchError("no size line found (expected `text data bss dec hex filename` or JSON)")


def budget_limits(cfg, target: str = "default") -> dict:
    b = (cfg.section("bench").get("budget") or {}).get(target)
    if not b:
        raise BenchError(f"no [bench.budget.{target}] with flash and ram limits in wz.toml")
    return {k: parse_bytes(b[k]) for k in ("flash", "ram") if k in b}


def budget_gate(sizes: dict, limits: dict) -> dict:
    """Each budget's used, limit, headroom and verdict; `pass` only when every limit holds."""
    out = {"pass": True, "checks": {}}
    for k, lim in limits.items():
        used = int(sizes[k])
        ok = used <= lim
        out["checks"][k] = {"used": used, "limit": lim, "headroom": lim - used, "pct": round(100 * used / lim, 1), "pass": ok}
        out["pass"] = out["pass"] and ok
    return out


# ---- parity: the host reference must match the device byte for byte ------------------------------------------------
def split_records(data: bytes, record) -> list[bytes]:
    if record in (None, "line"):
        return data.splitlines(keepends=False)
    n = int(record)
    if n <= 0:
        raise BenchError("record size must be positive")
    return [data[i:i + n] for i in range(0, len(data), n)]


def parity(device: bytes, host: bytes, record="line") -> dict:
    """Compare two record streams. `equal` only when both have the same records, in order, byte for byte."""
    dev_recs, host_recs = split_records(device, record), split_records(host, record)
    first = None
    for i, (a, b) in enumerate(zip(dev_recs, host_recs)):
        if a != b:
            off = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
            first = {"record": i, "byte": off, "device": a[:64].hex(), "host": b[:64].hex()}
            break
    if first is None and len(dev_recs) != len(host_recs):
        first = {"record": min(len(dev_recs), len(host_recs)), "byte": 0, "device": "", "host": "",
                 "note": f"record counts differ ({len(dev_recs)} device, {len(host_recs)} host)"}
    same = sum(1 for a, b in zip(dev_recs, host_recs) if a == b)
    return {"equal": first is None and device == host, "records_device": len(dev_recs), "records_host": len(host_recs),
            "records_equal": same, "first_difference": first,
            "sha256_device": hashlib.sha256(device).hexdigest(), "sha256_host": hashlib.sha256(host).hexdigest()}


# ---- instruments over SCPI (raw TCP, port 5025 by convention) -----------------------------------------------------
def parse_addr(addr: str) -> tuple[str, int]:
    host, _, port = str(addr).rpartition(":")
    if not host:
        return str(addr), 5025
    return host, int(port)


def scpi_query(addr: str, command: str, timeout: float = 5.0) -> str:
    host, port = parse_addr(addr)
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(command.strip().encode() + b"\n")
        if not command.strip().endswith("?"):
            return ""
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    return buf.decode(errors="replace").strip()


def _number(raw: str):
    try:
        return float(raw.split(",")[0])
    except ValueError:
        return None


def capture(cfg, instrument: str, read: dict, timeout: float = 5.0) -> dict:
    r = cfg.resources().get(instrument)
    if not r:
        raise BenchError(f"unknown instrument {instrument!r}")
    addr = r.get("scpi")
    if not addr:
        raise BenchError(f"[resources.{instrument}] has no scpi address (host:port)")
    idn = scpi_query(addr, "*IDN?", timeout)
    fields = {}
    for name, q in read.items():
        raw = scpi_query(addr, q, timeout)
        fields[name] = {"query": q, "raw": raw, "value": _number(raw), "at": iso()}
    return {"instrument": instrument, "address": addr, "idn": idn, "fields": fields}


# ---- scenarios ------------------------------------------------------------------------------------------------------
def load_scenario(path: Path) -> dict:
    path = Path(path)
    try:
        sc = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise BenchError(f"{path}: {e}") from None
    sc.setdefault("name", path.stem)
    sc["_path"] = str(path.resolve())
    sc["_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    steps = sc.get("step") or []
    if not steps:
        raise BenchError(f"{path}: no [[step]] entries")
    for i, st in enumerate(steps):
        if st.get("kind") not in KINDS:
            raise BenchError(f"{path}: step {i + 1} kind {st.get('kind')!r} (kinds: {', '.join(KINDS)})")
    return sc


def scenario_resources(sc: dict) -> list[str]:
    names = [sc[k] for k in ("device", "phone") if sc.get(k)] + list(sc.get("instruments", []))
    names += [st["instrument"] for st in sc.get("step", []) if st.get("instrument")]
    names += [st["resource"] for st in sc.get("step", []) if st.get("resource")]
    return sorted(set(names))


def check_rules(cfg, sc: dict) -> None:
    """Device rules from wz.toml that no scenario may break."""
    res = cfg.resources()
    for n in scenario_resources(sc):
        if n not in res:
            raise BenchError(f"scenario names {n!r}, which is not a [resources.*] entry")
        if res[n].get("protected"):
            raise BenchError(f"{n} is protected (the owner's own device); no scenario may lease or drive it")
    dev, phone = sc.get("device"), sc.get("phone")
    if dev and phone:
        only = res[dev].get("pair_only_with")
        if only and only != phone:
            raise BenchError(f"{dev}'s pairing slot is reserved to {only}; this scenario would pair it with {phone}")
    if phone and res[phone].get("kind") not in (None, "phone"):
        raise BenchError(f"{phone} is not a phone (kind {res[phone].get('kind')!r})")


def _fill(cmd: str, ctx: dict) -> str:
    def sub(m):
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        raise BenchError(f"unknown placeholder {{{key}}} in {cmd!r}")
    return re.sub(r"\{([A-Za-z0-9_.-]+)\}", sub, cmd)


def _context(cfg, sc: dict, run_dir: Path, commit: str) -> dict:
    ctx = {"run": str(run_dir), "commit": commit, "scenario": sc["name"]}
    for slot in ("device", "phone"):
        if sc.get(slot):
            ctx[slot] = sc[slot]
            for k, v in cfg.resources()[sc[slot]].items():
                ctx[f"{slot}.{k}"] = v
    for n in scenario_resources(sc):
        for k, v in cfg.resources()[n].items():
            ctx[f"{n}.{k}"] = v
    return ctx


def _commit(cwd: Path) -> str:
    p = subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else "unknown"


def _sh(cmd: str, cwd: Path, log: Path, timeout_s: float) -> tuple[int, str]:
    rc, timed_out = worker.execute(["/bin/sh", "-c", cmd], cwd, dict(os.environ), timeout_s, log,
                                   log.with_suffix(".err"))
    out = log.read_text() if log.exists() else ""
    err = log.with_suffix(".err").read_text() if log.with_suffix(".err").exists() else ""
    return (124 if timed_out else rc), out + err


def _next_run_id(base: Path, name: str) -> str:
    base.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for p in base.iterdir() if (m := re.match(rf"^{re.escape(name)}-(\d+)$", p.name))]
    return f"{name}-{max(nums, default=0) + 1:03d}"


def runs_dir(cfg) -> Path:
    return cfg.root / cfg.section("bench").get("evidence_dir", "bench/runs")


def run(cfg, scenario: Path, cwd: Path | None = None, holder: str | None = None, say=print,
        hand_poll_s: float = 2.0) -> dict:
    """Run one scenario under its leases. Returns the run record (also evidence.json in the run directory)."""
    sc = load_scenario(scenario)
    check_rules(cfg, sc)
    cwd = Path(cwd or (Path(sc["_path"]).parent / sc.get("cwd", "."))).resolve()
    names = scenario_resources(sc)
    holder = holder or os.environ.get("WZ_JOB") or os.environ.get("WZ_ROLE") or "owner"
    reuse = leases.inherited(cfg, names)
    need = [n for n in names if n not in reuse]
    fds = leases.acquire(cfg, need, holder, hold_s=parse_duration(sc.get("timeout", "2h"))) if need else []
    if fds is None:
        raise BenchError(f"a resource of {', '.join(names)} is leased by someone else; see `wz lease list`")
    commit = _commit(cwd)
    run_id = _next_run_id(runs_dir(cfg), sc["name"])
    run_dir = runs_dir(cfg) / run_id
    run_dir.mkdir(parents=True)
    ctx = _context(cfg, sc, run_dir, commit)
    rec = {"run": run_id, "scenario": sc["name"], "scenario_file": sc["_path"], "scenario_digest": sc["_digest"],
           "commit": commit, "by": holder, "agent": bool(os.environ.get("WZ_ROLE")), "device": sc.get("device"),
           "phone": sc.get("phone"), "leases": names, "started": iso(), "steps": [], "fields": [], "verdict": "running"}

    def field(step, name, value, source):
        rec["fields"].append({"step": step, "field": name, "value": value, "source": source})

    def stop(verdict, why):
        rec.update(verdict=verdict, why=why)

    try:
        for i, st in enumerate(sc["step"], 1):
            kind = st["kind"]
            label = f"{i:02d}-{kind}"
            res_used = [x for x in ([sc.get("device")] if kind in DEVICE_KINDS else []) +
                        ([sc.get("phone")] if kind == "app" else []) + [st.get("instrument"), st.get("resource")] if x]
            step = {"n": i, "kind": kind, "started": iso()}
            rec["steps"].append(step)
            try:
                hands.require_attended(cfg, res_used, f"step {i} ({kind})")
            except hands.HandError as e:
                step.update(verdict="refused", why=str(e))
                stop("blocked", str(e))
                break
            timeout_s = parse_duration(st.get("timeout", "30m"))
            if kind == "hand":
                h = hands.ask(cfg, st["text"], by=holder, job=os.environ.get("WZ_JOB"), resource=st.get("resource"),
                              why=st.get("why", f"bench run {run_id}"), timeout=st.get("timeout", "2h"))
                say(f"{label}: waiting on {h['id']}: {h['text']}")
                h = hands.wait(cfg, h["id"], poll_s=hand_poll_s)
                step.update(hand=h["id"], verdict="pass" if h["status"] == "done" else "fail", status=h["status"])
                field(i, f"{h['id']}.status", h["status"], f"hands/{h['id']}.json")
                if h["status"] != "done":
                    stop("blocked", f"hand-step {h['id']} {h['status']}")
                    break
                continue
            if kind == "capture":
                try:
                    cap = capture(cfg, st["instrument"], st.get("read", {}))
                except (OSError, BenchError) as e:
                    step.update(verdict="fail", why=f"{e.__class__.__name__}: {e}")
                    stop("fail", f"capture from {st['instrument']}: {e}")
                    break
                path = run_dir / f"{label}-{st['instrument']}.json"
                write_json(path, cap)
                vals = {k: v["value"] for k, v in cap["fields"].items()}
                for k, v in cap["fields"].items():
                    field(i, f"{st['instrument']}.{k}", v["value"], f"{path.name} ({v['query']} -> {v['raw']!r}; {cap['idn']})")
                bad = hands.out_of_limits(cfg, vals, st.get("limits"))
                step.update(evidence=path.name, readings=vals)
                if bad:
                    step.update(verdict="fail", why="; ".join(bad))
                    _safe_state(cfg, sc, ctx, cwd, run_dir, step)
                    worker.halt(cfg, os.environ.get("WZ_ROLE") or "all", f"bench {run_id}: limit crossed: {'; '.join(bad)}", by=holder)
                    stop("halted", f"safety limit crossed: {'; '.join(bad)}")
                    break
                step["verdict"] = "pass"
                continue
            cmd = _fill(st["run"], ctx) if st.get("run") else None
            if kind == "parity":
                if cmd:
                    rc, out = _sh(cmd, cwd, run_dir / f"{label}.log", timeout_s)
                    if rc != 0:
                        step.update(verdict="fail", rc=rc, why="host reference replay failed")
                        stop("fail", f"step {i} host replay exited {rc}")
                        break
                dev_p, host_p = Path(_fill(st["device"], ctx)), Path(_fill(st["host"], ctx))
                try:
                    p = parity(dev_p.read_bytes(), host_p.read_bytes(), st.get("record", "line"))
                except OSError as e:
                    step.update(verdict="fail", why=str(e))
                    stop("fail", f"parity: {e}")
                    break
                write_json(run_dir / f"{label}.json", p)
                step.update(evidence=f"{label}.json", **{k: p[k] for k in ("equal", "records_device", "records_host")})
                field(i, "parity.records_equal", f"{p['records_equal']}/{p['records_device']}", f"{label}.json")
                field(i, "parity.sha256_device", p["sha256_device"][:16], dev_p.name)
                field(i, "parity.sha256_host", p["sha256_host"][:16], host_p.name)
                if not p["equal"]:
                    step["verdict"] = "fail"
                    stop("fail", f"parity: first difference at record {p['first_difference']['record']}")
                    break
                step["verdict"] = "pass"
                continue
            if not cmd:
                raise BenchError(f"step {i} ({kind}) needs run = \"<command>\"")
            rc, out = _sh(cmd, cwd, run_dir / f"{label}.log", timeout_s)
            step.update(cmd=cmd, rc=rc, log=f"{label}.log", finished=iso())
            field(i, f"{kind}.exit", rc, f"{label}.log")
            if rc != 0:
                step["verdict"] = "fail"
                stop("fail", f"step {i} ({kind}) exited {rc}" + (" (timed out)" if rc == 124 else ""))
                break
            if kind == "firmware" and (st.get("size") or st.get("size_file")):
                if st.get("size"):
                    _rc, text = _sh(_fill(st["size"], ctx), cwd, run_dir / f"{label}-size.log", 120)
                    size_src = f"{label}-size.log"
                else:
                    sp = cwd / _fill(st["size_file"], ctx)
                    text, size_src = sp.read_text(), str(sp.relative_to(run_dir) if sp.is_relative_to(run_dir) else sp)
                g = budget_gate(parse_size(text), budget_limits(cfg, st.get("budget", "default")))
                write_json(run_dir / f"{label}-budget.json", g)
                step.update(budget=g)
                for k, c in g["checks"].items():
                    field(i, f"budget.{k}", f"{c['used']} of {c['limit']} B ({c['pct']} %)", size_src)
                if not g["pass"]:
                    step["verdict"] = "fail"
                    over = [k for k, c in g["checks"].items() if not c["pass"]]
                    stop("fail", f"over budget: {', '.join(over)}")
                    break
            if kind == "records" and st.get("out"):
                p = run_dir / _fill(st["out"], ctx)
                if not p.is_file():
                    step["verdict"] = "fail"
                    stop("fail", f"records step wrote no {p.name}")
                    break
                field(i, "records.bytes", p.stat().st_size, p.name)
            step["verdict"] = "pass"
        else:
            rec["verdict"] = "pass"
    except Exception as e:
        stop("error", f"{e.__class__.__name__}: {e}")
        raise
    finally:
        rec["finished"] = iso()
        leases.release(cfg, need, fds)
        write_json(run_dir / "evidence.json", rec)
        (run_dir / "REPORT.md").write_text(report(rec))
        flags.event(cfg, holder, "bench", run_id, f"{sc['name']} at {commit[:12]}: {rec['verdict']}" +
                    (f" ({rec.get('why')})" if rec.get("why") else ""))
    return rec


def _safe_state(cfg, sc, ctx, cwd, run_dir, step) -> None:
    cmd = sc.get("safe_state")
    if cmd:
        rc, _ = _sh(_fill(cmd, ctx), cwd, run_dir / "safe-state.log", 60)
        step["safe_state_rc"] = rc


def report(rec: dict) -> str:
    lines = [f"# Bench run {rec['run']}: {rec['verdict']}", "",
             f"Scenario `{rec['scenario']}` (digest {rec['scenario_digest']}) at commit `{rec['commit'][:12]}`, by "
             f"{rec['by']}{' (agent)' if rec.get('agent') else ''}; device {rec.get('device') or '-'}, phone "
             f"{rec.get('phone') or '-'}; leases {', '.join(rec['leases']) or '-'}; {rec['started']} to {rec.get('finished', '')}.", ""]
    if rec.get("why"):
        lines += [f"Stopped: {rec['why']}", ""]
    lines += ["| step | kind | verdict | note |", "|---|---|---|---|"]
    for s in rec["steps"]:
        note = s.get("why") or s.get("cmd") or s.get("hand") or s.get("evidence") or ""
        lines.append(f"| {s['n']} | {s['kind']} | {s.get('verdict', '')} | {str(note).replace('|', '/')[:90]} |")
    lines += ["", "## Fields read", "", "Each value below was read from the file named beside it, in this run directory.", "",
              "| step | field | value | read from |", "|---|---|---|---|"]
    for f in rec["fields"]:
        lines.append(f"| {f['step']} | {f['field']} | {f['value']} | {str(f['source']).replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def all_runs(cfg) -> list[dict]:
    d = runs_dir(cfg)
    if not d.is_dir():
        return []
    return [r for p in sorted(d.glob("*/evidence.json")) if isinstance(r := read_json(p), dict)]


def ready_for_owner(cfg, scenario: Path, commit: str | None = None) -> dict:
    """The agent's passing run of this exact scenario at this commit; refuses when there is none.

    The owner is never the first tester: hand the scenario over only with this run's report."""
    sc = load_scenario(scenario)
    commit = commit or _commit(Path(sc["_path"]).parent)
    for r in reversed(all_runs(cfg)):
        if (r.get("scenario_digest") == sc["_digest"] and r.get("commit") == commit and r.get("verdict") == "pass"
                and r.get("agent")):
            return r
    raise BenchError(f"no agent has passed scenario {sc['name']} (digest {sc['_digest']}) at {commit[:12]}; "
                     "the owner is never the first tester")

