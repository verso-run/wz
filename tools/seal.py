#!/usr/bin/env python3
"""Fill the installer's sha256 into INSTALL-PROMPT.md, START-HERE.md and README.md, and check the pinned release agrees everywhere.

    python3 tools/seal.py          # write
    python3 tools/seal.py --check  # exit 1 if anything is out of step (the test suite does this)
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHA_RE = re.compile(r"^  ([0-9a-f]{64}|@@INSTALL_SHA@@)$", re.M)


def state():
    install = (ROOT / "install.sh").read_bytes()
    sha = hashlib.sha256(install).hexdigest()
    ref = re.search(r'WZ_REF="\$\{WZ_REF:-([^}]+)\}"', install.decode()).group(1)
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    return sha, ref, version


def prompt_text(sha: str) -> str:
    return SHA_RE.sub(f"  {sha}", (ROOT / "INSTALL-PROMPT.md").read_text())


PAGES = ("START-HERE.md", "README.md")  # pages that show the whole prompt between PROMPT markers


def with_prompt(name: str, sha: str) -> str:
    text = (ROOT / name).read_text()
    a, b = text.index("<!-- PROMPT -->"), text.index("<!-- /PROMPT -->")
    return text[:a] + "<!-- PROMPT -->\n```text\n" + prompt_text(sha) + "```\n" + text[b:]


def problems() -> list[str]:
    sha, ref, version = state()
    out = []
    if ref != f"v{version}":
        out.append(f"install.sh pins {ref} but pyproject.toml is version {version}")
    for name in ("INSTALL-PROMPT.md", *PAGES):
        if f"/{ref}/" not in (ROOT / name).read_text():
            out.append(f"{name} does not pin {ref}")
    if (ROOT / "INSTALL-PROMPT.md").read_text() != prompt_text(sha):
        out.append("INSTALL-PROMPT.md does not carry the sha256 of install.sh")
    for name in PAGES:
        if (ROOT / name).read_text() != with_prompt(name, sha):
            out.append(f"{name} differs from INSTALL-PROMPT.md or carries a stale sha256")
    return out


if __name__ == "__main__":
    if "--check" in sys.argv:
        bad = problems()
        print("\n".join(bad) or "in step")
        sys.exit(1 if bad else 0)
    sha, _, _ = state()
    (ROOT / "INSTALL-PROMPT.md").write_text(prompt_text(sha))
    for name in PAGES:
        (ROOT / name).write_text(with_prompt(name, sha))
    print("sealed", sha)
