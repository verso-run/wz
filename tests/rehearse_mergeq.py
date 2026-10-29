"""Rehearsal of the merge queue on a scratch repo, printed for a human: six finished jobs, one of them red.

    python3 tests/rehearse_mergeq.py /some/empty/scratch/dir

Uses the stand-in `claude` of the tests (no network, no tokens). The gate fails whenever src/job-0004.txt is in the tree, so
job-0004 is the red PR; expect it bounced alone, the other five landed, and every commit on integration clean.
"""
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
from conftest import answers, make_repo  # noqa: E402
from wz import jobs, merge, setup_mode, worker  # noqa: E402

root = pathlib.Path(sys.argv[1]).resolve()
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True)
os.environ.update(GIT_AUTHOR_NAME="rehearsal", GIT_AUTHOR_EMAIL="rehearsal", GIT_COMMITTER_NAME="rehearsal",
                  GIT_COMMITTER_EMAIL="rehearsal", GIT_CONFIG_GLOBAL=str(root / "gitconfig"), XDG_CONFIG_HOME=str(root / "xdg"))
(root / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
make_repo(root / "app")
(root / "office").mkdir()
log = root / "gates.log"
cfg = setup_mode.apply(answers(root, checks=[f"echo gate-pass >> {log}", "test ! -f src/job-0004.txt"]), root / "ws", git_init=False)
for _ in range(6):
    jobs.add(cfg, "app", "change")
    worker.serve(cfg, role="app", wait=True, say=lambda *_: None)
app = cfg.store_root("app")


def g(*a):
    return subprocess.run(["git", "-C", str(app), *a], capture_output=True, text=True).stdout.strip()


print("integration before:", g("rev-parse", "--short", "integration"))
print("--- wz merge (job-0004 is the red PR)")
merge.merge(cfg, say=print)
print("--- gate passes run:", log.read_text().count("gate-pass"), "(one at a time would be 6)")
print("--- job files on integration:", sorted(f for f in g("ls-tree", "-r", "--name-only", "integration").split() if f.startswith("src/job")))
print("--- job states:", {j["id"]: (j.get("merged") and "merged" or j.get("merge_refused")) for j in jobs.all_jobs(cfg)})
print("--- every first-parent commit on integration:")
for sha in g("rev-list", "--first-parent", "--reverse", "main..integration").split():
    red = subprocess.run(["git", "-C", str(app), "cat-file", "-e", f"{sha}:src/job-0004.txt"], capture_output=True).returncode == 0
    print("   ", sha[:9], "CONTAINS the red change" if red else "clean")
print("--- second merge tick:", merge.merge(cfg, say=print))
