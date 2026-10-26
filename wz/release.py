"""Build and release: rings and their gates, artifacts pinned by hash, holds with an expiry, freezes, the live read.

Rings ([rings] order = ["lab", "dev", "prod"]; sign = ["prod"]). Each ring may say, under [rings.<ring>]:
  gates      commands that must pass before an artifact enters the ring; each runs with WZ_ARTIFACT (the file)
             and WZ_ARTIFACT_SHA256, so a gate reads the artifact itself, never a label or a tag
  deploy     the command that puts a pinned artifact on the ring (on a signed ring it runs only through a sign)
  rollback   the command that puts the previous pin back; `wz ring rehearse` runs deploy -> rollback -> deploy on a
             non-signed ring and records that the revert path works before it is ever needed
  health_url a JSON endpoint the ring serves; `wz ring read <ring> <field>` writes what it read as evidence

Pins (status/pins/<ring>.json): {"artifact", "sha256", "params"}. A pin carries parameters only, never logic: the
hard invariants live in the code, and [release] pin_params lists the parameter names a pin may set.

Holds (`wz hold add`): a finding against a ref (a store, a ring, a commit or a job) at a level:
  BLOCKS        stops promote and any signed act on that ref until cleared
  INCONCLUSIVE  read exactly like BLOCKS: an unfinished check is not a pass
  NOTE          shown, never blocks
  FREEZE        a presign window on a store: the merge step does not move its integration branch, so the candidate
                the owner is signing cannot change under them
Every hold has an expiry; an expired hold stops blocking and the watchdog says so. Only the lead clears a hold, and
only by naming a decision row (`wz hold clear <id> --decision D-12`), so a cleared finding has a written reason.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from . import flags
from .util import iso, locked, now, parse_duration, read_json, write_json

LEVELS = ("BLOCKS", "INCONCLUSIVE", "NOTE", "FREEZE")
STOPS = {"BLOCKS", "INCONCLUSIVE"}


class ReleaseError(Exception):
    pass


# ---- holds ----------------------------------------------------------------------------------------------------------
def _hdir(cfg):
    return cfg.state / "holds"


def hold_add(cfg, ref: str, level: str, text: str, evidence: str = "", expires="7d", by: str = "") -> dict:
    level = level.upper()
    if level not in LEVELS:
        raise ReleaseError(f"level must be one of {', '.join(LEVELS)}")
    if not text.strip():
        raise ReleaseError("a hold states its finding in one sentence")
    if level in STOPS and not evidence:
        raise ReleaseError(f"a {level} hold names the evidence that proves it")
    with locked(cfg.state / "holds.lock"):
        nums = [int(m.group(1)) for p in _hdir(cfg).glob("hold-*.json") if (m := re.match(r"hold-(\d+)", p.stem))]
        t = now()
        h = {"id": f"hold-{max(nums, default=0) + 1:04d}", "ref": ref, "level": level, "text": text.strip(),
             "evidence": evidence, "by": by or os.environ.get("WZ_ROLE", "owner"), "created": iso(t), "created_t": t,
             "expires_t": t + parse_duration(expires), "expires": iso(t + parse_duration(expires))}
        write_json(_hdir(cfg) / f"{h['id']}.json", h)
    flags.event(cfg, h["by"], "hold", h["id"], f"{level} on {ref}: {text.strip()}")
    return h


def holds(cfg, t: float | None = None) -> list[dict]:
    t = now() if t is None else t
    out = []
    for p in sorted(_hdir(cfg).glob("hold-*.json")):
        h = read_json(p)
        if isinstance(h, dict):
            h["state"] = "cleared" if h.get("cleared") else ("expired" if t > h.get("expires_t", 0) else "open")
            out.append(h)
    return out


def open_holds(cfg, ref: str | None = None, levels=None) -> list[dict]:
    return [h for h in holds(cfg) if h["state"] == "open" and (ref is None or h["ref"] in (ref, "all"))
            and (levels is None or h["level"] in levels)]


def hold_clear(cfg, hid: str, decision: str, by: str = "") -> dict:
    text = (cfg.root / "DECISIONS.md").read_text() if (cfg.root / "DECISIONS.md").exists() else ""
    if not re.search(rf"^\| {re.escape(decision)} \|", text, re.M):
        raise ReleaseError(f"{decision} is not a row in DECISIONS.md; a hold is cleared only by a recorded decision")
    p = _hdir(cfg) / f"{hid}.json"
    h = read_json(p)
    if not isinstance(h, dict):
        raise ReleaseError(f"no hold {hid}")
    h.update(cleared=iso(), cleared_by=by or os.environ.get("WZ_ROLE", "owner"), decision=decision)
    write_json(p, h)
    flags.event(cfg, h["cleared_by"], "hold", hid, f"cleared by {decision}")
    return h


def check_not_held(cfg, *refs: str) -> None:
    for ref in refs:
        if not ref:
            continue
        hs = open_holds(cfg, ref, STOPS)
        if hs:
            raise ReleaseError(f"{ref} is held: " + "; ".join(f"{h['id']} {h['level']}: {h['text']}" for h in hs))


def frozen(cfg, store: str) -> dict | None:
    hs = open_holds(cfg, store, {"FREEZE"})
    return hs[0] if hs else None


# ---- pins and gates -------------------------------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pin_path(cfg, ring: str) -> Path:
    return cfg.root / "status" / "pins" / f"{ring}.json"


def ring_conf(cfg, ring: str) -> dict:
    r = cfg.rings()
    if ring not in r.get("order", []):
        raise ReleaseError(f"unknown ring {ring!r} (rings: {', '.join(r.get('order', []))})")
    v = r.get(ring, {})
    return v if isinstance(v, dict) else {}


def check_params(cfg, params: dict) -> None:
    allowed = set(cfg.section("release").get("pin_params", []))
    for k, v in params.items():
        if k not in allowed:
            raise ReleaseError(f"pin parameter {k!r} is not in [release] pin_params; a pin carries parameters only, "
                               "and every one is declared")
        if isinstance(v, (dict, list)):
            raise ReleaseError(f"pin parameter {k!r} must be a single value, not a structure")


def pin(cfg, ring: str, artifact: Path, params: dict | None = None, by: str = "") -> dict:
    ring_conf(cfg, ring)
    params = params or {}
    check_params(cfg, params)
    artifact = Path(artifact).resolve()
    rec = {"ring": ring, "artifact": str(artifact), "sha256": sha256_file(artifact), "params": params,
           "pinned": iso(), "by": by or os.environ.get("WZ_ROLE", "owner")}
    prev = read_json(_pin_path(cfg, ring))
    if isinstance(prev, dict):
        rec["previous"] = {k: prev.get(k) for k in ("artifact", "sha256", "params")}
    write_json(_pin_path(cfg, ring), rec)
    return rec


def read_pin(cfg, ring: str) -> dict:
    p = read_json(_pin_path(cfg, ring))
    if not isinstance(p, dict):
        raise ReleaseError(f"nothing is pinned for {ring}")
    check_params(cfg, p.get("params", {}))
    return p


def gate(cfg, ring: str, artifact: Path | None = None) -> dict:
    """Run a ring's gates against the pinned artifact. The artifact's hash is checked before and after the gates."""
    conf = ring_conf(cfg, ring)
    p = read_pin(cfg, ring)
    art = Path(artifact or p["artifact"]).resolve()
    sha = sha256_file(art)
    if sha != p["sha256"]:
        raise ReleaseError(f"{art.name} hashes to {sha[:12]}, the {ring} pin says {p['sha256'][:12]}; gates read the "
                           "pinned artifact, never a label")
    env = dict(os.environ, WZ_ARTIFACT=str(art), WZ_ARTIFACT_SHA256=sha, WZ_RING=ring,
               WZ_PIN_PARAMS=json.dumps(p.get("params", {}), sort_keys=True))
    results, ok = [], True
    for cmd in conf.get("gates", []):
        c = subprocess.run(cmd, shell=True, cwd=str(cfg.root), env=env, capture_output=True, text=True)
        results.append({"gate": cmd, "rc": c.returncode, "tail": (c.stdout + c.stderr)[-600:]})
        if c.returncode != 0:
            ok = False
            break
    after = sha256_file(art)
    if after != sha:
        ok = False
        results.append({"gate": "(artifact unchanged)", "rc": 1, "tail": f"artifact changed during the gates: {after[:12]}"})
    rec = {"ring": ring, "sha256": sha, "artifact": str(art), "pass": ok, "gates": results, "at": iso()}
    out = cfg.root / "status" / "releases" / sha[:12] / f"{ring}-gate.json"
    write_json(out, rec)
    rec["evidence"] = str(out)
    flags.event(cfg, os.environ.get("WZ_ROLE", "owner"), "gate", ring, f"{sha[:12]}: {'pass' if ok else 'fail'}")
    return rec


def rehearse(cfg, ring: str) -> dict:
    """deploy -> rollback -> deploy on a ring that needs no sign; proves the revert path before it is needed."""
    if ring in cfg.rings().get("sign", []):
        raise ReleaseError(f"{ring} is a signed ring; rehearse the revert on a ring before it")
    conf = ring_conf(cfg, ring)
    if not conf.get("deploy") or not conf.get("rollback"):
        raise ReleaseError(f"[rings.{ring}] needs deploy and rollback commands to rehearse")
    p = read_pin(cfg, ring)
    steps = []
    for name in ("deploy", "rollback", "deploy"):
        env = dict(os.environ, WZ_ARTIFACT=p["artifact"], WZ_ARTIFACT_SHA256=p["sha256"], WZ_RING=ring)
        c = subprocess.run(conf[name], shell=True, cwd=str(cfg.root), env=env, capture_output=True, text=True)
        steps.append({"step": name, "rc": c.returncode, "tail": (c.stdout + c.stderr)[-400:]})
        if c.returncode != 0:
            break
    rec = {"ring": ring, "sha256": p["sha256"], "steps": steps, "pass": all(s["rc"] == 0 for s in steps) and len(steps) == 3,
           "at": iso()}
    write_json(cfg.root / "status" / "releases" / p["sha256"][:12] / f"{ring}-rehearsal.json", rec)
    return rec


# ---- shipped means read on the live ring ----------------------------------------------------------------------------
def _dig(obj, dotted: str):
    for part in dotted.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            raise ReleaseError(f"field {dotted!r} is not in what the ring served")
    return obj


def live_read(cfg, ring: str, field: str, timeout: float = 10) -> dict:
    """Read one field from the ring's health endpoint and keep it as evidence; this, not a merge, is 'live'."""
    url = ring_conf(cfg, ring).get("health_url")
    if not url:
        raise ReleaseError(f"[rings.{ring}] has no health_url")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    rec = {"ring": ring, "url": url, "field": field, "value": _dig(body, field), "read_at": iso()}
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", field)
    write_json(cfg.root / "status" / "live" / f"{ring}-{safe}.json", rec)
    return rec
