"""Signs: every release and outward act waits for the owner.

Anyone (a role, the lead, a timer) may ASK: `wz sign request "<what>" --cmd "<exact command>"` writes a request.
Only the owner SIGNS, from the owner's own shell (`wz sign approve <id>`) or the approval page, with a PIN that no
agent ever sees. A sign is a write-once file bound to the request's digest: if the request changes after the sign,
the sign no longer matches and nothing runs. `wz sign run <id>` performs a signed act exactly once.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess

from . import flags
from .util import iso, locked, now, read_json, write_json, write_once

PIN_ITER = 300_000
MAX_FAILS = 5
LOCKOUT_S = 900


class SignError(Exception):
    pass


def _d(cfg):
    return cfg.state / "approvals"


def owner_only(env=None) -> None:
    env = os.environ if env is None else env
    if env.get("WZ_ROLE"):
        raise SignError("signing is the owner's; it cannot run inside a role session (WZ_ROLE is set)")


def digest(req: dict) -> str:
    body = {k: req.get(k) for k in ("id", "what", "command", "action", "ring")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def request(cfg, what: str, command: str | None = None, action: dict | None = None, why: str = "",
            ring: str | None = None, by: str = "") -> dict:
    if not (command or action):
        raise SignError("a sign request needs the exact command (or action) it will run")
    d = _d(cfg)
    with locked(d / "seq.lock"):
        seq = read_json(d / "seq.json") or {"next": 1}
        rid = f"sign-{seq['next']:04d}"
        write_json(d / "seq.json", {"next": seq["next"] + 1})
    req = {"id": rid, "what": what, "why": why, "command": command, "action": action, "ring": ring,
           "by": by or os.environ.get("WZ_ROLE", "owner"), "created": iso()}
    req["digest"] = digest(req)
    write_once(d / "requests" / f"{rid}.json", req)
    flags.event(cfg, req["by"], "sign-request", rid, what)
    return req


def get(cfg, rid: str) -> dict:
    r = read_json(_d(cfg) / "requests" / f"{rid}.json")
    if not isinstance(r, dict):
        raise SignError(f"no sign request {rid}")
    return r


def status(cfg, rid: str) -> str:
    d = _d(cfg)
    for st in ("done", "denied", "signed"):
        if (d / st / f"{rid}.json").exists():
            return st
    return "pending"


def all_requests(cfg) -> list[dict]:
    p = _d(cfg) / "requests"
    out = []
    if p.is_dir():
        for f in sorted(p.glob("sign-*.json")):
            r = read_json(f)
            if isinstance(r, dict):
                r["status"] = status(cfg, r["id"])
                out.append(r)
    return out


def pending(cfg) -> list[dict]:
    return [r for r in all_requests(cfg) if r["status"] == "pending"]


# ---- the PIN -------------------------------------------------------------------------------------------------------
def set_pin(cfg, pin: str) -> None:
    if len(pin) < 6:
        raise SignError("the PIN must be at least 6 characters")
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITER)
    p = _d(cfg) / "pin.json"
    write_json(p, {"salt": salt.hex(), "hash": h.hex(), "iter": PIN_ITER, "set": iso()})
    os.chmod(p, 0o600)


def has_pin(cfg) -> bool:
    return (_d(cfg) / "pin.json").exists()


def verify_pin(cfg, pin: str) -> bool:
    d = _d(cfg)
    rec = read_json(d / "pin.json")
    if not rec:
        raise SignError("no PIN set; the owner runs `wz sign set-pin` first")
    with locked(d / "fails.lock"):
        fails = [t for t in (read_json(d / "fails.json") or []) if now() - t < LOCKOUT_S]
        if len(fails) >= MAX_FAILS:
            raise SignError(f"locked after {MAX_FAILS} wrong PINs; try again in {int(LOCKOUT_S - (now() - fails[0]))} s")
        h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(rec["salt"]), int(rec["iter"]))
        ok = hmac.compare_digest(h.hex(), rec["hash"])
        write_json(d / "fails.json", [] if ok else fails + [now()])
    return ok


# ---- sign, deny, run -----------------------------------------------------------------------------------------------
def sign(cfg, rid: str, pin: str, via: str = "terminal") -> dict:
    req = get(cfg, rid)
    if status(cfg, rid) != "pending":
        raise SignError(f"{rid} is already {status(cfg, rid)}")
    if not verify_pin(cfg, pin):
        raise SignError("wrong PIN")
    rec = {"id": rid, "digest": req["digest"], "at": iso(), "via": via}
    if not write_once(_d(cfg) / "signed" / f"{rid}.json", rec):
        raise SignError(f"{rid} was signed already")
    flags.event(cfg, "owner", "signed", rid, req["what"])
    return rec


def deny(cfg, rid: str, pin: str, why: str = "", via: str = "terminal") -> dict:
    get(cfg, rid)
    if status(cfg, rid) != "pending":
        raise SignError(f"{rid} is already {status(cfg, rid)}")
    if not verify_pin(cfg, pin):
        raise SignError("wrong PIN")
    rec = {"id": rid, "at": iso(), "why": why, "via": via}
    write_once(_d(cfg) / "denied" / f"{rid}.json", rec)
    flags.event(cfg, "owner", "denied", rid, why)
    return rec


def run(cfg, rid: str) -> dict:
    """Perform a signed act, once. Refuses an unsigned, denied, already-run or since-changed request."""
    req = get(cfg, rid)
    d = _d(cfg)
    signed = read_json(d / "signed" / f"{rid}.json")
    if (d / "denied" / f"{rid}.json").exists():
        raise SignError(f"{rid} was denied")
    if not signed:
        raise SignError(f"{rid} is not signed")
    if signed.get("digest") != digest(req) or req.get("digest") != digest(req):
        raise SignError(f"{rid} changed after it was signed; nothing runs")
    from . import release
    try:
        release.check_not_held(cfg, req.get("ring") or "", (req.get("action") or {}).get("store", ""),
                               (req.get("action") or {}).get("sha", ""))
    except release.ReleaseError as e:
        raise SignError(str(e)) from None
    if not write_once(d / "done" / f"{rid}.json", {"id": rid, "started": iso()}):
        raise SignError(f"{rid} has already run")
    if req.get("command"):
        p = subprocess.run(req["command"], shell=True, cwd=str(cfg.root), capture_output=True, text=True)
        out = {"rc": p.returncode, "output": (p.stdout + p.stderr)[-2000:]}
    else:
        out = _act(cfg, req["action"])
    rec = {"id": rid, "started": read_json(d / "done" / f"{rid}.json")["started"], "finished": iso(), **out}
    write_json(d / "done" / f"{rid}.json", rec)
    flags.event(cfg, "owner", "sign-run", rid, f"rc={out.get('rc')}")
    return rec


def _act(cfg, action: dict) -> dict:
    from .worker import _git
    if action.get("type") == "wake":
        return {"rc": 0, "output": "a wake needs no run: the sign is its approval (wz wake)"}
    if action.get("type") != "promote":
        return {"rc": 1, "output": f"unknown action {action.get('type')!r}"}
    s = cfg.stores()[action["store"]]
    repo = cfg.store_root(action["store"])
    main, sha = action["to"], action["sha"]
    if _git(repo, "merge-base", "--is-ancestor", main, sha, check=False).returncode != 0:
        return {"rc": 1, "output": f"{main} is not an ancestor of {sha[:12]}; refusing a non-fast-forward release"}
    old = _git(repo, "rev-parse", main).stdout.strip()
    _git(repo, "update-ref", f"refs/heads/{main}", sha, old)
    out = f"{main}: {old[:12]} -> {sha[:12]}"
    if s.get("remote"):
        p = _git(repo, "push", s["remote"], f"{sha}:refs/heads/{main}", check=False)
        out += f"; push rc={p.returncode} {p.stderr[-300:]}"
        return {"rc": p.returncode, "output": out}
    return {"rc": 0, "output": out}
