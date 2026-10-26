"""Small helpers shared by every wz module: time, atomic JSON files, locks, process checks, path globs."""
from __future__ import annotations

import contextlib
import datetime as _dt
import errno
import fcntl
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator


def now() -> float:
    return time.time()


def iso(t: float | None = None) -> str:
    """Local time in ISO 8601 with its UTC offset, to the second."""
    return _dt.datetime.fromtimestamp(now() if t is None else t).astimezone().isoformat(timespec="seconds")


def today(t: float | None = None) -> str:
    return _dt.datetime.fromtimestamp(now() if t is None else t).strftime("%Y-%m-%d")


def parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


_DUR = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$")


def parse_duration(v: Any) -> int:
    """'90s', '45m', '2h', '1d' or a bare number of seconds -> seconds."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    m = _DUR.match(str(v))
    if not m:
        raise ValueError(f"not a duration: {v!r} (use 90s, 45m, 2h or 1d)")
    n, unit = float(m.group(1)), m.group(2) or "s"
    return int(n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit])


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any) -> None:
    """Atomic: write a sibling temp file, then rename it over the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_once(path: Path, obj: Any) -> bool:
    """Create `path` holding `obj` only if it does not exist yet. False when it already exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    return True


def append_jsonl(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list:
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return out


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """An exclusive advisory lock on `path` (created if missing) for the body of the with-block."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def try_lock(path: Path) -> int | None:
    """Non-blocking exclusive lock. Returns the open fd (keep it open to hold the lock), or None if another process holds it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        os.close(fd)
        if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            return None
        raise
    return fd


def pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def glob_to_regex(glob: str) -> re.Pattern:
    """A path glob with `**` (any depth, including none), `*` (within one segment) and `?`."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(rel: str, glob: str) -> bool:
    """True when the relative path `rel` matches `glob`; `dir/**` also matches `dir` itself."""
    rel, glob = rel.strip("/"), glob.strip("/")
    if glob.endswith("/**") and rel == glob[:-3]:
        return True
    return bool(glob_to_regex(glob).match(rel))


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
