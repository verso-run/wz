import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _seal():
    spec = importlib.util.spec_from_file_location("seal", ROOT / "tools" / "seal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prompt_page_and_installer_agree():
    assert _seal().problems() == []


@pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")
@pytest.mark.parametrize("name", ["install.sh", "uninstall.sh"])
def test_scripts_parse(name):
    assert subprocess.run(["sh", "-n", str(ROOT / name)]).returncode == 0


def test_installer_never_touches_sudo_or_unsafe_modes():
    text = (ROOT / "install.sh").read_text() + (ROOT / "uninstall.sh").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "sudo " not in code.replace("without sudo", "")
    assert "bypassPermissions" not in code
    for line in code.splitlines():
        if "install timers" in line:
            assert "--uninstall" in line, line


def test_prompt_states_the_safe_rules():
    p = (ROOT / "INSTALL-PROMPT.md").read_text()
    for needle in ("Never use sudo", "Ask me before anything that costs money", "safe to run twice",
                   "Never turn on timers", "wz init --simple --print-charter"):
        assert needle in p, needle
