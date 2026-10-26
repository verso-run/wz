"""The budget cap: model spend per account per day, read from each job's own reported cost.

[budget] daily_usd caps the whole project; [accounts.<name>] daily_usd caps one account. A role with no account is
charged to the project only. `wz serve` starts no job while either cap is spent; running jobs are never stopped.
"""
from __future__ import annotations

from .util import append_jsonl, now, read_jsonl, today


def _log(cfg):
    return cfg.state / "budget.jsonl"


def record(cfg, role: str, job: str, usd: float) -> None:
    acct = cfg.role(role).get("account", "") if role in cfg.roles() else ""
    append_jsonl(_log(cfg), {"t": now(), "day": today(), "role": role, "account": acct, "job": job, "usd": round(float(usd or 0), 4)})


def spent(cfg, account: str | None = None, day: str | None = None) -> float:
    day = day or today()
    return round(sum(r.get("usd", 0) for r in read_jsonl(_log(cfg))
                     if r.get("day") == day and (account is None or r.get("account") == account)), 4)


def allowed(cfg, role: str) -> tuple[bool, str]:
    cap = cfg.section("budget").get("daily_usd")
    if cap is not None and spent(cfg) >= float(cap):
        return False, f"project budget spent today ({spent(cfg):.2f} of {float(cap):.2f} USD)"
    acct = cfg.role(role).get("account")
    if acct:
        acap = cfg.account(acct).get("daily_usd")
        if acap is not None and spent(cfg, acct) >= float(acap):
            return False, f"account {acct} budget spent today ({spent(cfg, acct):.2f} of {float(acap):.2f} USD)"
    return True, ""


def table(cfg, day: str | None = None) -> list[dict]:
    rows = []
    cap = cfg.section("budget").get("daily_usd")
    rows.append({"account": "(project)", "spent": spent(cfg, None, day), "cap": cap})
    for name, a in cfg.section("accounts").items():
        rows.append({"account": name, "spent": spent(cfg, name, day), "cap": a.get("daily_usd")})
    return rows
