"""The owner's commands that change the team without hand-editing wz.toml: `wz role`, `wz rule`, `wz owns` (add and remove).

Each change is made on the text of wz.toml (comments and order stay), checked three ways before anything is written (the
edited file parses to exactly the intended settings; wz accepts it; the paths of different roles do not overlap), saved
with a backup of the old file, and followed by rebuilding the charters. Only the owner runs these: a role session cannot.
"""
from __future__ import annotations

import difflib
import os
import re
import tomllib
from pathlib import Path

from . import charters, config, jobs, packs, tomltext
from .util import iso

KEEP_BACKUPS = 30


class TeamError(Exception):
    pass


# ---- overlap between two path globs -----------------------------------------------------------------------------------
def _tokens(glob: str) -> list[list[tuple]]:
    """A glob as token lists (a `**/` may match nothing, so it gives two lists): ('c', ch) ('?',) ('*',) ('**',)."""
    out: list[list[tuple]] = [[]]
    i = 0
    g = glob.strip("/")
    while i < len(g):
        if g.startswith("**/", i):
            out = [x + y for x in out for y in ([], [("**",), ("c", "/")])]
            i += 3
        elif g.startswith("**", i):
            out = [x + [("**",)] for x in out]
            i += 2
        elif g[i] == "*":
            out = [x + [("*",)] for x in out]
            i += 1
        elif g[i] == "?":
            out = [x + [("?",)] for x in out]
            i += 1
        else:
            out = [x + [("c", g[i])] for x in out]
            i += 1
    return out


def _meet(p: list, q: list) -> bool:
    n, m = len(p), len(q)
    seen: dict = {}

    def star(tok):
        return tok[0] in ("*", "**")

    def eat(st, other):          # may the star `st` absorb the token `other`?
        return other[0] != "c" or other[1] != "/" or st[0] == "**"

    def go(i, j):
        if (i, j) in seen:
            return seen[i, j]
        seen[i, j] = False
        if i == n and j == m:
            r = True
        else:
            r = False
            if i < n and star(p[i]):
                r = go(i + 1, j) or (j < m and eat(p[i], q[j]) and go(i, j + 1))
            if not r and j < m and star(q[j]):
                r = go(i, j + 1) or (i < n and eat(q[j], p[i]) and go(i + 1, j))
            if not r and i < n and j < m and not star(p[i]) and not star(q[j]):
                a, b = p[i], q[j]
                ok = (a[0] == "?" and b[0] == "?") or (a[0] == "c" and b[0] == "c" and a[1] == b[1]) or \
                     (a[0] == "?" and b[0] == "c" and b[1] != "/") or (b[0] == "?" and a[0] == "c" and a[1] != "/")
                r = ok and go(i + 1, j + 1)
        seen[i, j] = r
        return r

    return go(0, 0)


def globs_overlap(a: str, b: str) -> bool:
    """True when some path matches both globs (`dir/**` also matches `dir` itself, as the guard does)."""
    def forms(g):
        g = g.strip("/")
        return [g] + ([g[:-3]] if g.endswith("/**") else [])
    return any(_meet(p, q) for x in forms(a) for y in forms(b) for p in _tokens(x) for q in _tokens(y))


def _check_glob(glob: str) -> str:
    g = glob.strip()
    while g.startswith("./"):
        g = g[2:]
    if not g or g.startswith("/") or g.startswith("~") or ".." in g.split("/") or "\\" in g:
        raise TeamError(f"{glob!r} is not a path inside the store: write it relative to the store's folder, "
                        f"like `src/**` (a folder and everything in it) or `README.md` (one file)")
    return g


def _overlaps(cfg_roles: dict, role: str, store: str, glob: str) -> list[tuple[str, str]]:
    return [(other, g) for other, r in cfg_roles.items() if other != role
            for g in r["owns"].get(store, []) if globs_overlap(glob, g)]


def _refuse_overlap(role: str, store: str, glob: str, hits: list[tuple[str, str]]) -> None:
    if not hits:
        return
    other, g = hits[0]
    raise TeamError(
        f"not changed: `{glob}` in {store} overlaps `{g}`, which {other} owns. Each path has one owner, so two roles could "
        f"overwrite each other's work. Either pick a path that does not overlap, or first take it from {other}: "
        f"wz owns remove {other} {store} '{g}'")


# ---- the edit machinery ---------------------------------------------------------------------------------------------------
class Edit:
    """A pending change to wz.toml: the old text, the new text, and the settings the new text must parse to."""

    def __init__(self, cfg: config.Config):
        self.cfg = cfg
        self.raw = cfg.path.read_text()
        self.old = self.raw if self.raw.endswith("\n") else self.raw + "\n"
        self.text = self.old
        self.want = tomllib.loads(self.raw)
        self.notes: list[str] = []

    def tables(self):
        return tomltext.scan(self.text)

    def role_table(self, role: str) -> tomltext.Table:
        tab = tomltext.find(self.tables(), ("roles", role))
        if tab is None or tomltext.has_dotted_keys(tab):
            raise TeamError(self.by_hand(f"[roles.{role}] is written in a form I do not edit"))
        return tab

    @staticmethod
    def by_hand(why: str) -> str:
        return (f"not changed: {why}. Open wz.toml and make the change there, then run `wz charters`.")

    # -- pieces
    def add_to_array(self, tab: tomltext.Table, key: str, item: str) -> None:
        k = tab.keys.get(key)
        lit = tomltext.literal(item)
        if k is None:
            self.text = tomltext.insert_line(self.text, tab.body_end, f"{key} = [{lit}]")
        else:
            self.text = tomltext.array_add(self.text, k.val_start, k.val_end, lit)

    def remove_from_array(self, tab: tomltext.Table, key: str, item: str) -> bool:
        k = tab.keys.get(key)
        if k is None:
            return False
        items = tomltext.array_items(self.text, k.val_start, k.val_end)
        for n, (a, b) in enumerate(items):
            try:
                v = tomllib.loads(f"x = {self.text[a:b]}")["x"]
            except tomllib.TOMLDecodeError:
                continue
            if v == item:
                self.text = tomltext.array_remove(self.text, k.val_start, k.val_end, n)
                return True
        return False

    def seed_owns(self, role: str) -> None:
        """A role with no `owns` of its own uses its pack's. Writing a table for it would replace those defaults, so write
        them out first (and say so)."""
        r = self.want["roles"][role]
        if "owns" in r:
            return
        seed = {k: list(v) for k, v in packs.PACKS.get(r.get("pack", "software"), {}).get("owns", {}).items()}
        r["owns"] = seed
        if not seed:
            return
        tab = self.role_table(role)
        lines = [f"[roles.{role}.owns]"] + [f"{tomltext_key(s)} = [{', '.join(tomltext.literal(g) for g in gl)}]"
                                           for s, gl in seed.items()]
        self.text = tomltext.insert_line(self.text, tab.body_end, "\n".join(lines))
        self.notes.append(f"{role} had no paths of its own, so it was using the defaults of its {r.get('pack', 'software')} "
                          f"pack. Those are now written out in wz.toml ({', '.join(f'{s}: ' + ', '.join(g) for s, g in seed.items())}) "
                          f"so your change adds to them instead of replacing them.")

    # -- finishing
    def finish(self, *, dry_run: bool, what: str) -> str:
        """Check the new text, then (unless a dry run) back up, replace the file and rebuild the charters. Returns the report."""
        cfg = self.cfg
        try:
            got = tomllib.loads(self.text)
        except tomllib.TOMLDecodeError as e:
            raise TeamError(self.by_hand(f"the edited file did not parse ({e})")) from None
        if got != self.want:
            raise TeamError(self.by_hand("wz.toml is written in a form where I cannot make this change without risking "
                                         "a different meaning"))
        probe = config.Config(cfg.path, got)
        errs = probe.validate()
        if errs:
            raise TeamError("not changed: wz would not accept the result:\n  " + "\n  ".join(errs))
        diff = [ln for ln in difflib.unified_diff(self.old.splitlines(), self.text.splitlines(), lineterm="", n=0)
                if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
        if not diff:
            return f"Nothing to change: {what}"
        out = [what, "", "In wz.toml:"] + ["  " + ln for ln in diff]
        out += [""] + self.notes
        if dry_run:
            return "\n".join(["DRY RUN, nothing was written. If you ran it for real:", ""] + out)
        if cfg.path.read_text() != self.raw:
            raise TeamError("not changed: wz.toml was changed by something else while I was working; run the command again")
        backup = self.backup()
        tmp = cfg.path.with_name(cfg.path.name + ".new")
        try:
            tmp.write_text(self.text)
            os.replace(tmp, cfg.path)
        finally:
            tmp.unlink(missing_ok=True)
        try:
            new_cfg = config.load(cfg.path)
            before = _charter_texts(new_cfg)
            charters.write_all(new_cfg)
            changed = _changed(new_cfg, before)
        except Exception as e:            # put the old file back rather than leave wz.toml and the charters disagreeing
            cfg.path.write_text(backup.read_text())
            raise TeamError(f"not changed: rebuilding the charters failed ({e}); wz.toml is back as it was") from None
        out.append(f"Old wz.toml kept at {backup}. To undo: copy it back over wz.toml and run `wz charters`.")
        out.append("Charters rebuilt: " + (", ".join(changed) if changed else "(none changed)"))
        out.append("A role session that is already open keeps its old charter until it is restarted: `wz cli <role> --restart`.")
        return "\n".join(out)

    def backup(self) -> Path:
        d = self.cfg.state / "backups"
        d.mkdir(parents=True, exist_ok=True)
        stamp = iso()[:19].replace(":", "").replace("-", "").replace("T", "-")
        p, n = d / f"wz.toml.{stamp}", 1
        while p.exists():
            n += 1
            p = d / f"wz.toml.{stamp}-{n}"
        p.write_text(self.cfg.path.read_text())
        for old in sorted(d.glob("wz.toml.*"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
        return p


def tomltext_key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else tomltext.literal(k)


def _charter_texts(cfg) -> dict[str, str]:
    out = {}
    for role in cfg.roles():
        p = cfg.charter_path(role)
        out[f"roles/{role}/CHARTER.md"] = p.read_text() if p.is_file() else ""
    p = cfg.root / "AGENTS.md"
    out["AGENTS.md"] = p.read_text() if p.is_file() else ""
    return out


def _changed(cfg, before: dict[str, str]) -> list[str]:
    after = _charter_texts(cfg)
    return [k for k, v in after.items() if before.get(k) != v]


def owner_only(env=None) -> None:
    env = os.environ if env is None else env
    if env.get("WZ_ROLE"):
        raise TeamError("changing the team, its paths and its rules is the owner's, from the owner's own terminal; it cannot "
                        "run inside a role session. Put the request in your report, with the exact command, and stop.")


def _begin(cfg, role: str | None = None) -> Edit:
    owner_only()
    if role is not None and role not in cfg.roles():
        raise TeamError(f"there is no role called {role!r}. The roles are: {', '.join(cfg.roles())}")
    return Edit(cfg)


# ---- the commands -----------------------------------------------------------------------------------------------------
def rule_add(cfg, role: str, rule: str, dry_run: bool = False) -> str:
    rule = " ".join(rule.split())
    if not rule:
        raise TeamError("the rule is empty: give it as one sentence in quotes")
    ed = _begin(cfg, role)
    have = cfg.role(role)["rules"]
    if rule in have:
        return f"Nothing to change: {role} already has this rule."
    ed.want["roles"][role].setdefault("rules", []).append(rule)
    ed.add_to_array(ed.role_table(role), "rules", rule)
    return ed.finish(dry_run=dry_run, what=f"Added a rule to {role}: {rule}")


def rule_remove(cfg, role: str, rule: str, dry_run: bool = False) -> str:
    rule = " ".join(rule.split())
    ed = _begin(cfg, role)
    own = ed.want["roles"][role].get("rules", [])
    if rule not in own:
        if rule in packs.PACKS.get(cfg.role(role)["pack"], {}).get("rules", []):
            raise TeamError(f"not changed: that rule comes with {role}'s {cfg.role(role)['pack']} pack, not from wz.toml, "
                            f"so this command cannot take it away. Only rules added with `wz rule add` can be removed.")
        raise TeamError(f"not changed: {role} has no added rule that reads exactly {rule!r}. Its added rules are:"
                        + "".join(f"\n  - {r}" for r in own or ["(none)"]))
    own.remove(rule)
    if not ed.remove_from_array(ed.role_table(role), "rules", rule):
        raise TeamError(ed.by_hand("I could not find that rule in the file"))
    if not own:                                    # the list is empty now: drop it (the pack's rules are separate)
        del ed.want["roles"][role]["rules"]
        k = ed.role_table(role).keys["rules"]
        ed.text = tomltext.remove_range(ed.text, k.line_start, k.line_end)
    return ed.finish(dry_run=dry_run, what=f"Removed a rule from {role}: {rule}")


def _store_check(cfg, store: str) -> None:
    if store not in cfg.stores():
        raise TeamError(f"there is no store called {store!r}. The stores are: {', '.join(cfg.stores())}")


def owns_add(cfg, role: str, store: str, glob: str, dry_run: bool = False) -> str:
    ed = _begin(cfg, role)
    _store_check(cfg, store)
    glob = _check_glob(glob)
    roles = cfg.roles()
    mine = roles[role]["owns"].get(store, [])
    if glob in mine:
        return f"Nothing to change: {role} already owns {glob} in {store}."
    cover = next((g for g in mine if _covers(g, glob)), None)
    if cover:
        return f"Nothing to change: {role} already owns {glob} in {store}, through `{cover}`."
    _refuse_overlap(role, store, glob, _overlaps(roles, role, store, glob))
    ed.seed_owns(role)
    owns = ed.want["roles"][role]["owns"]
    owns.setdefault(store, []).append(glob)
    tab = tomltext.find(ed.tables(), ("roles", role, "owns"))
    if tab is None:
        if "owns" in ed.cfg.section("roles")[role]:
            raise TeamError(ed.by_hand(f"[roles.{role}] sets `owns` in a form I do not edit"))
        rt = ed.role_table(role)
        ed.text = tomltext.insert_line(ed.text, rt.body_end, f"[roles.{role}.owns]\n{tomltext_key(store)} = [{tomltext.literal(glob)}]")
    else:
        if tomltext.has_dotted_keys(tab):
            raise TeamError(ed.by_hand(f"[roles.{role}.owns] is written in a form I do not edit"))
        ed.add_to_array(tab, store, glob)
    return ed.finish(dry_run=dry_run, what=f"{role} now owns {glob} in {store}.")


def _covers(broad: str, narrow: str) -> bool:
    """True when every path `narrow` matches is also matched by `broad` (checked on the shapes wz.toml actually uses)."""
    if broad.endswith("/**"):
        base = broad[:-3]
        return narrow == base or narrow.startswith(base + "/")
    return False


def owns_remove(cfg, role: str, store: str, glob: str, dry_run: bool = False) -> str:
    ed = _begin(cfg, role)
    _store_check(cfg, store)
    glob = _check_glob(glob)
    mine = cfg.role(role)["owns"].get(store, [])
    if glob not in mine:
        raise TeamError(f"not changed: {role} does not own {glob!r} in {store}. It owns: "
                        + (", ".join(mine) if mine else "nothing there"))
    ed.seed_owns(role)
    ed.want["roles"][role]["owns"][store].remove(glob)
    tab = tomltext.find(ed.tables(), ("roles", role, "owns"))
    if tab is None or tomltext.has_dotted_keys(tab) or not ed.remove_from_array(tab, store, glob):
        raise TeamError(ed.by_hand(f"I could not find {glob} under [roles.{role}.owns] in the file"))
    if not ed.want["roles"][role]["owns"][store]:
        # nothing left in that store: drop the empty list, and the table too unless the pack's defaults would then return
        del ed.want["roles"][role]["owns"][store]
        tab = tomltext.find(ed.tables(), ("roles", role, "owns"))
        k = tab.keys[store]
        ed.text = tomltext.remove_range(ed.text, k.line_start, k.line_end)
        tab = tomltext.find(ed.tables(), ("roles", role, "owns"))
        if not tab.keys and not ed.want["roles"][role]["owns"] and not packs.PACKS[cfg.role(role)["pack"]].get("owns"):
            del ed.want["roles"][role]["owns"]
            ed.text = tomltext.remove_range(ed.text, tab.header_start, tab.body_end)
    return ed.finish(dry_run=dry_run, what=f"{role} no longer owns {glob} in {store}.")


def role_add(cfg, name: str, pack: str, *, store: str | None = None, owns: list[str] | None = None, desc: str = "",
             model: str = "", account: str = "", cap: int | None = None, web: bool = False, dry_run: bool = False) -> str:
    ed = _begin(cfg)
    if name in cfg.roles():
        raise TeamError(f"not changed: there is already a role called {name!r}")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name):
        raise TeamError(f"{name!r} is not a usable role name: lowercase letters, digits and dashes, starting with a letter")
    if pack not in packs.PACKS:
        raise TeamError(f"there is no pack called {pack!r}. The packs are: {', '.join(packs.PACKS)}")
    if pack == packs.LEAD:
        raise TeamError(f"not changed: there is already a lead ({cfg.lead()}) and a project has exactly one")
    if store is not None:
        _store_check(cfg, store)
    pairs = []
    for spec in owns or []:
        s, sep, g = spec.partition("=")
        if not sep:
            raise TeamError(f"--owns wants STORE=PATH, for example --owns app='src/**' (you wrote {spec!r})")
        _store_check(cfg, s)
        pairs.append((s, _check_glob(g)))
    roles = cfg.roles()
    for i, (s, g) in enumerate(pairs):
        _refuse_overlap(name, s, g, _overlaps(roles, name, s, g))
        for s2, g2 in pairs[:i]:
            if s2 == s and globs_overlap(g, g2) and g != g2:
                raise TeamError(f"not changed: `{g}` and `{g2}` in {s} overlap each other; list only the wider one")
    if account and account not in cfg.section("accounts"):
        raise TeamError(f"there is no account called {account!r}. The accounts are: {', '.join(cfg.section('accounts')) or '(none)'}")
    block: dict = {"pack": pack}
    if store:
        block["store"] = store
    for k, v in (("desc", desc), ("model", model), ("account", account)):
        if v:
            block[k] = v
    if cap is not None:
        block["cap"] = cap
    if web:
        block["web"] = True
    lines = [f"[roles.{name}]"] + [f"{k} = {config._val(v)}" for k, v in block.items()]
    if pairs:
        by_store: dict[str, list[str]] = {}
        for s, g in pairs:
            if g not in by_store.setdefault(s, []):
                by_store[s].append(g)
        block["owns"] = by_store
        lines += [f"[roles.{name}.owns]"] + [f"{tomltext_key(s)} = {config._val(gl)}" for s, gl in by_store.items()]
    ed.want.setdefault("roles", {})[name] = block
    tabs = [t for t in ed.tables() if t.path and t.path[:1] == ("roles",)]
    at = max((t.body_end for t in tabs), default=len(ed.text))
    ed.text = tomltext.insert_line(ed.text, at, ("\n" if at else "") + "\n".join(lines))
    if not pairs and not packs.PACKS[pack].get("owns"):
        ed.notes.append(f"{name} owns no paths yet, so the guard lets it write only its own roles/{name}/ folder, the Report "
                        f"section of its briefs and its ledger rows. Give it work with: wz owns add {name} <store> '<path>'")
    out = ed.finish(dry_run=dry_run, what=f"Added the role {name} ({pack} pack).")
    return out


def role_remove(cfg, name: str, dry_run: bool = False) -> str:
    ed = _begin(cfg, name)
    if cfg.is_lead(name):
        raise TeamError(f"not changed: {name} is the lead, and a project needs exactly one")
    busy = [j for j in jobs.all_jobs(cfg, name) if j.get("status") in ("queued", "held", "running")]
    if busy:
        raise TeamError(f"not changed: {name} still has {len(busy)} job(s) queued, held or running ("
                        + ", ".join(j["id"] for j in busy[:5]) + "). Cancel them first with `wz job cancel <id>`.")
    mine = [t for t in ed.tables() if t.path and t.path[:2] == ("roles", name)]
    if not mine:
        raise TeamError(ed.by_hand(f"[roles.{name}] is written in a form I do not edit"))
    del ed.want["roles"][name]
    for t in reversed(mine):
        ed.text = tomltext.remove_range(ed.text, t.header_start, t.body_end)
    ed.notes.append(f"{name}'s folder roles/{name}/ (its notes, lessons and charter) is left in place, as is its history. "
                    f"If it has an open session, close it with `wz park {name}`.")
    return ed.finish(dry_run=dry_run, what=f"Removed the role {name}.")
