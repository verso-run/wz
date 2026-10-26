"""The files a public repository needs, and the workflow rules the public scan depends on."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_community_files_exist():
    for name in ["SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", ".github/pull_request_template.md",
                 ".github/ISSUE_TEMPLATE/bug.yml", ".github/ISSUE_TEMPLATE/feature.yml", ".github/dependabot.yml"]:
        assert (ROOT / name).is_file(), name


def test_every_workflow_is_read_only_by_default():
    assert WORKFLOWS
    for w in WORKFLOWS:
        assert re.search(r"^permissions:\n  contents: read\n", w.read_text(), re.M), w.name


def test_every_action_is_pinned_to_a_full_sha_with_a_version_comment():
    seen = 0
    for w in WORKFLOWS:
        for line in w.read_text().splitlines():
            m = re.match(r"\s*-?\s*uses:\s*(\S+)(.*)$", line)
            if not m:
                continue
            seen += 1
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)), (w.name, line)
            assert re.fullmatch(r"\s+# v\d[\w.]*\s*", m.group(2)), (w.name, line)
    assert seen


def test_secret_scan_runs_on_push_and_pull_request_with_a_checked_binary():
    s = (ROOT / ".github" / "workflows" / "secret-scan.yml").read_text()
    assert "push:" in s and "pull_request:" in s
    assert re.search(r'GITLEAKS_SHA256: "[0-9a-f]{64}"', s) and "sha256sum -c" in s
    assert "fetch-depth: 0" in s


def test_dependabot_covers_actions_and_pip():
    s = (ROOT / ".github" / "dependabot.yml").read_text()
    assert 'package-ecosystem: "github-actions"' in s and 'package-ecosystem: "pip"' in s


def test_no_personal_email_in_any_tracked_file():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    bad = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        for m in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", p.read_text(errors="ignore")):
            if not (m.endswith("@example.org") or m.endswith("@example.com") or m.endswith("@users.noreply.github.com")):
                bad.append((f, m))
    assert not bad, bad[:5]
