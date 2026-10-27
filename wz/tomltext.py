"""Edit wz.toml as text, so the owner's comments, order and spacing survive (Python reads TOML but cannot write it back).

This is a small scanner, not a TOML parser: it finds where each [table] and `key = value` sits and returns offsets, and the
edits below insert or delete only the text they need. It does not have to be right about every legal TOML form, because the
caller parses the edited text with `tomllib` and refuses the change unless the result is exactly the intended data.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field


class Unsupported(Exception):
    """The file is written in a form this scanner will not edit (the caller says so and changes nothing)."""


@dataclass
class Key:
    name: str
    line_start: int
    val_start: int
    val_end: int
    line_end: int          # just past the newline that ends the line


@dataclass
class Table:
    path: tuple | None     # None for an [[array table]]; () before the first header
    header_start: int
    body_end: int          # just past the last key line (or the header line when there are none)
    keys: dict = field(default_factory=dict)


def _skip_string(t: str, i: int) -> int:
    """`i` is at a quote; return the index just past the string."""
    q = t[i]
    if t.startswith(q * 3, i):
        j = i + 3
        while j < len(t):
            if q == '"' and t[j] == "\\":
                j += 2
                continue
            if t.startswith(q * 3, j):
                j += 3
                while j < len(t) and t[j] == q:     # up to two extra quotes may belong to the string
                    j += 1
                return j
            j += 1
        raise Unsupported("an unterminated string")
    j = i + 1
    while j < len(t) and t[j] != "\n":
        if q == '"' and t[j] == "\\":
            j += 2
            continue
        if t[j] == q:
            return j + 1
        j += 1
    raise Unsupported("an unterminated string")


def _skip_value(t: str, i: int) -> int:
    """`i` is at the first character of a value; return the index just past it."""
    c = t[i] if i < len(t) else ""
    if c in "\"'":
        return _skip_string(t, i)
    if c in "[{":
        depth, j = 0, i
        while j < len(t):
            ch = t[j]
            if ch in "\"'":
                j = _skip_string(t, j)
                continue
            if ch == "#":
                while j < len(t) and t[j] != "\n":
                    j += 1
                continue
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        raise Unsupported("an unclosed bracket")
    j = i
    while j < len(t) and t[j] not in "\n#,":
        j += 1
    while j > i and t[j - 1] in " \t\r":
        j -= 1
    return j


def _line_end(t: str, i: int) -> int:
    j = t.find("\n", i)
    return len(t) if j < 0 else j + 1


def _header_path(line: str) -> tuple:
    d = tomllib.loads(line + "\n")
    path = []
    while d:
        (k, v), = d.items()
        path.append(k)
        d = v if isinstance(v, dict) else {}
    return tuple(path)


def scan(t: str) -> list[Table]:
    """Every table in the text, in file order, with the keys written directly under it."""
    tables = [Table((), 0, 0)]
    i, n = 0, len(t)
    while i < n:
        ls = i
        i = _line_end(t, ls)
        body = t[ls:i].strip()
        if not body or body.startswith("#"):
            continue
        if body.startswith("["):
            if body.startswith("[["):
                tables.append(Table(None, ls, i))
                continue
            j = ls + (len(t[ls:i]) - len(t[ls:i].lstrip()))
            k = j + 1
            while k < i and t[k] != "]":
                k = _skip_string(t, k) if t[k] in "\"'" else k + 1
            tables.append(Table(_header_path(t[j:k + 1]), ls, i))
            continue
        # a key line: key = value
        j = ls
        while t[j] in " \t":
            j += 1
        k = j
        while k < n and t[k] != "=" and t[k] != "\n":
            k = _skip_string(t, k) if t[k] in "\"'" else k + 1
        if k >= n or t[k] != "=":
            raise Unsupported("a line that is neither a table nor a key")
        name_text = t[j:k].strip()
        v = k + 1
        while v < n and t[v] in " \t":
            v += 1
        e = _skip_value(t, v)
        i = _line_end(t, e)
        tab = tables[-1]
        try:
            (key, probe), = tomllib.loads(f"{name_text} = 0").items()
        except (tomllib.TOMLDecodeError, ValueError):
            raise Unsupported(f"the key {name_text!r}") from None
        # a dotted key (a = 1 written as x.y = 1) is recorded under ".x.y" so a caller can refuse to edit around it
        tab.keys[key if not isinstance(probe, dict) else "." + name_text] = Key(key, ls, v, e, i)
        tab.body_end = i
    return tables


def find(tables: list[Table], path: tuple) -> Table | None:
    for tb in tables:
        if tb.path == path:
            return tb
    return None


def has_dotted_keys(tab: Table) -> bool:
    return any(k.startswith(".") for k in tab.keys)


# ---- arrays of strings ----------------------------------------------------------------------------------------------
def array_items(t: str, s: int, e: int) -> list[tuple[int, int]]:
    """Offsets of each top-level item of the array that spans t[s:e] (which starts with `[` and ends with `]`)."""
    out, i = [], s + 1
    while i < e - 1:
        c = t[i]
        if c in " \t\r\n,":
            i += 1
        elif c == "#":
            i = t.find("\n", i)
            i = e if i < 0 else i
        else:
            j = _skip_value(t, i)
            out.append((i, j))
            i = j
    return out


def array_add(t: str, s: int, e: int, item: str) -> str:
    """Insert `item` (already a TOML literal) as the last element of the array at t[s:e]."""
    items = array_items(t, s, e)
    close = e - 1
    if not items:
        return t[:s + 1] + item + t[s + 1:]
    last_end = items[-1][1]
    multiline = "\n" in t[last_end:close]
    if not multiline:
        return t[:last_end] + ", " + item + t[last_end:]
    after = last_end
    while after < close and t[after] in " \t":
        after += 1
    comma_end = after + 1 if t[after] == "," else None
    le = t.find("\n", last_end)
    indent = _indent_of(t, items[-1][0])
    if comma_end is None:
        t = t[:last_end] + "," + t[last_end:]
        le += 1
    return t[:le] + "\n" + indent + item + "," + t[le:]


def _indent_of(t: str, i: int) -> str:
    ls = t.rfind("\n", 0, i) + 1
    return re.match(r"[ \t]*", t[ls:]).group(0)


def array_remove(t: str, s: int, e: int, index: int) -> str:
    """Delete the element at `index` of the array at t[s:e], with its comma (and its line when it has one to itself)."""
    items = array_items(t, s, e)
    a, b = items[index]
    ls = t.rfind("\n", 0, a) + 1
    le = _line_end(t, b)
    before, after = t[ls:a], t[b:le]
    own_line = not before.strip() and re.fullmatch(r"[ \t]*,?[ \t]*(#[^\n]*)?\r?\n?", after) and "]" not in t[b:le]
    if own_line:
        return t[:ls] + t[le:]
    j = b
    while j < e and t[j] in " \t":
        j += 1
    if j < e and t[j] == ",":                      # take the comma after it and the space that follows
        j += 1
        while j < e and t[j] in " \t":
            j += 1
        return t[:a] + t[j:]
    k = a                                          # the last element: take the comma before it
    while k > s and t[k - 1] in " \t\r\n":
        k -= 1
    if k > s and t[k - 1] == ",":
        return t[:k - 1] + t[b:]
    return t[:a] + t[b:]


def literal(s: str) -> str:
    """A string as a TOML basic-string literal."""
    import json
    return json.dumps(s, ensure_ascii=False)


def insert_line(t: str, pos: int, line: str) -> str:
    """Insert one whole line at `pos` (the start of a line, or the end of the text)."""
    if pos == len(t) and t and not t.endswith("\n"):
        t += "\n"
        pos += 1
    return t[:pos] + line.rstrip("\n") + "\n" + t[pos:]


def remove_range(t: str, a: int, b: int) -> str:
    """Delete t[a:b] and, when that leaves two blank lines side by side, one of them."""
    head, tail = t[:a], t[b:]
    while head.endswith("\n\n") and tail.startswith("\n"):
        tail = tail[1:]
    return head + tail
