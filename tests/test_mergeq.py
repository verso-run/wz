"""The merge queue: batch, gate once, bisect a red batch to the bad branch. The engine tests use bare git repos only
(no jobs, no config); the last tests run it through `wz merge` on job records."""
import random

import pytest

from conftest import answers, git, make_repo
from wz import jobs, merge, mergeq, setup_mode, worker

QUIET = dict(say=lambda *_: None)


def branch(repo, name, files: dict, base="integration"):
    """A branch off `base` adding `files` (name -> text) in one commit."""
    git(repo, "checkout", "-q", "-b", name, base)
    for f, t in files.items():
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text(t)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", name)
    git(repo, "checkout", "-q", base)
    return mergeq.Entry(name, name, "app")


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path / "app")
    git(r, "branch", "integration")
    git(r, "checkout", "-q", "integration")
    return r


def gate_log(repo, tmp_path, bad="bad.txt"):
    """A gate that fails when `bad` exists in the tree, and logs each pass (file listing) to a file."""
    log = tmp_path / "gate.log"
    return [f"ls src >> {log}; echo --- >> {log}; test -z \"$(ls {bad} 2>/dev/null)\""], log


def tree(repo, ref="integration"):
    return set(git(repo, "ls-tree", "-r", "--name-only", ref).splitlines())


def verdicts(out):
    return {v["job"]: v["verdict"] for v in out["verdicts"]}


def test_green_batch_runs_the_gate_once(repo, tmp_path):
    es = [branch(repo, f"b{i}", {f"src/b{i}.txt": "x"}) for i in range(5)]
    checks, log = gate_log(repo, tmp_path)
    out = mergeq.run_queue(repo, "integration", es, checks, **QUIET)
    assert set(verdicts(out).values()) == {"merged"} and out["gate_runs"] == 1
    assert tree(repo) >= {f"src/b{i}.txt" for i in range(5)}
    assert log.read_text().count("---") == 1
    assert git(repo, "rev-parse", "integration") == out["verdicts"][-1]["sha"]


def test_red_branch_in_the_middle_is_bounced_alone(repo, tmp_path):
    names = ["a", "b", "c", "d", "e", "f"]
    es = [branch(repo, n, {f"src/{n}.txt": "x", **({"bad.txt": "boom"} if n == "d" else {})}) for n in names]
    checks, _ = gate_log(repo, tmp_path)
    out = mergeq.run_queue(repo, "integration", es, checks, **QUIET)
    assert verdicts(out) == {n: ("red" if n == "d" else "merged") for n in names}
    assert "bad.txt" not in tree(repo) and tree(repo) >= {f"src/{n}.txt" for n in "abcef"}
    red = next(v for v in out["verdicts"] if v["verdict"] == "red")
    assert "bad.txt" in red["check"] and red["bisected"] == 6
    assert out["gate_runs"] <= 1 + 3 + 1 + 1     # whole batch, log2(6) probes, the base check, the re-stacked remainder


def test_first_branch_red_and_last_branch_red(repo, tmp_path):
    checks, _ = gate_log(repo, tmp_path)
    es = [branch(repo, "a", {"bad.txt": "x"}), branch(repo, "b", {"src/b.txt": "x"}), branch(repo, "c", {"src/c.txt": "x"})]
    assert verdicts(mergeq.run_queue(repo, "integration", es, checks, **QUIET)) == {"a": "red", "b": "merged", "c": "merged"}
    es = [branch(repo, "d", {"src/d.txt": "x"}, base="integration"), branch(repo, "e", {"bad2.txt": "x", "bad.txt": "y"})]
    assert verdicts(mergeq.run_queue(repo, "integration", es, checks, **QUIET)) == {"d": "merged", "e": "red"}


def test_two_bad_branches_both_bounced_the_rest_land(repo, tmp_path):
    checks, _ = gate_log(repo, tmp_path)
    es = [branch(repo, n, {f"src/{n}.txt": "x", **({"bad.txt": "y"} if n in "bf" else {})}) for n in "abcdefg"]
    out = mergeq.run_queue(repo, "integration", es, checks, **QUIET)
    assert verdicts(out) == {n: ("red" if n in "bf" else "merged") for n in "abcdefg"}
    assert "bad.txt" not in tree(repo)


def test_red_only_together_is_blamed_on_the_later_branch(repo, tmp_path):
    """x and y are each fine alone and red together: the earlier one lands, the later one is bounced."""
    es = [branch(repo, "x", {"x.txt": "1"}), branch(repo, "y", {"y.txt": "1"}), branch(repo, "z", {"src/z.txt": "1"})]
    out = mergeq.run_queue(repo, "integration", es, ["! (test -f x.txt && test -f y.txt)"], **QUIET)
    assert verdicts(out) == {"x": "merged", "y": "red", "z": "merged"}


def test_tip_itself_red_blames_nobody_and_moves_nothing(repo, tmp_path):
    es = [branch(repo, "a", {"src/a.txt": "1"}), branch(repo, "b", {"src/b.txt": "1"})]
    before = git(repo, "rev-parse", "integration")
    out = mergeq.run_queue(repo, "integration", es, ["false"], **QUIET)
    assert set(verdicts(out).values()) == {"base-red"}
    assert git(repo, "rev-parse", "integration") == before


def test_conflict_is_bounced_alone(repo, tmp_path):
    es = [branch(repo, "a", {"src/shared.txt": "from a\n"}), branch(repo, "b", {"src/shared.txt": "from b\n"}),
          branch(repo, "c", {"src/c.txt": "1"})]
    out = mergeq.run_queue(repo, "integration", es, ["true"], **QUIET)
    assert verdicts(out) == {"a": "merged", "b": "conflict", "c": "merged"} and out["gate_runs"] == 1


def test_batch_max_splits_the_queue(repo, tmp_path):
    es = [branch(repo, f"b{i}", {f"src/b{i}.txt": "x"}) for i in range(7)]
    checks, log = gate_log(repo, tmp_path)
    out = mergeq.run_queue(repo, "integration", es, checks, batch_max=3, **QUIET)
    assert out["batches"] == 3 and out["gate_runs"] == 3 and len(out["landed"]) == 7


def test_gate_budget_leaves_the_rest_waiting(repo, tmp_path):
    checks, _ = gate_log(repo, tmp_path)
    es = [branch(repo, n, {f"src/{n}.txt": "x", **({"bad.txt": "y"} if n == "c" else {})}) for n in "abcd"]
    out = mergeq.run_queue(repo, "integration", es, checks, max_gate_runs=1, **QUIET)
    assert out["verdicts"] == [] and out["gate_runs"] == 1
    assert "bad.txt" not in tree(repo) and "src/a.txt" not in tree(repo)      # nothing moved without a green pass


def test_dry_run_moves_nothing_but_finds_the_bad_one(repo, tmp_path):
    checks, _ = gate_log(repo, tmp_path)
    es = [branch(repo, n, {f"src/{n}.txt": "x", **({"bad.txt": "y"} if n == "b" else {})}) for n in "abc"]
    before = git(repo, "rev-parse", "integration")
    out = mergeq.run_queue(repo, "integration", es, checks, dry_run=True, **QUIET)
    assert verdicts(out) == {"a": "would-merge", "b": "red", "c": "would-merge"}
    assert git(repo, "rev-parse", "integration") == before


def test_integration_moved_underneath_is_not_overwritten(repo, tmp_path):
    es = [branch(repo, "a", {"src/a.txt": "x"})]
    # the gate itself advances integration, as a concurrent merger would
    git(repo, "checkout", "-q", "--detach")
    mover = f"git -C {repo} update-ref refs/heads/integration $(git -C {repo} commit-tree -m other -p integration integration^{{tree}})"
    out = mergeq.run_queue(repo, "integration", es, [mover], **QUIET)
    assert out["verdicts"] == [] and "src/a.txt" not in tree(repo)     # no verdict: it stays queued for the next tick


@pytest.mark.parametrize("seed", range(12))
def test_random_batches_land_exactly_the_good_ones(repo, tmp_path, seed):
    rnd = random.Random(seed)
    n = rnd.randint(1, 9)
    badset = {i for i in range(n) if rnd.random() < 0.3}
    es = [branch(repo, f"b{i}", {f"src/b{i}.txt": "x", **({f"bad-{i}.txt": "x"} if i in badset else {})}) for i in range(n)]
    checks, _ = gate_log(repo, tmp_path, bad="bad-*.txt")
    out = mergeq.run_queue(repo, "integration", es, checks, **QUIET)
    got = verdicts(out)
    assert got == {f"b{i}": ("red" if i in badset else "merged") for i in range(n)}
    assert not [f for f in tree(repo) if f.startswith("bad-")]
    assert out["gate_runs"] <= 1 + len(badset) * (n.bit_length() + 2)


# ---- through `wz merge` on job records ---------------------------------------------------------------------------

def make_done_jobs(cfg, n):
    ids = []
    for _ in range(n):
        j = jobs.add(cfg, "app", "change")
        worker.serve(cfg, role="app", wait=True, **QUIET)
        assert jobs.get(cfg, j["id"])["status"] == "done"
        ids.append(j["id"])
    return ids


def test_rehearsal_red_job_in_a_batch_is_bounced_alone(tmp_path):
    make_repo(tmp_path / "app")
    (tmp_path / "office").mkdir()
    log = tmp_path / "gates.log"
    checks = [f"echo pass >> {log}", "test ! -f src/job-0004.txt"]
    cfg = setup_mode.apply(answers(tmp_path, checks=checks), tmp_path / "ws", git_init=False)
    ids = make_done_jobs(cfg, 6)
    app = cfg.store_root("app")
    before = git(app, "rev-parse", "integration")
    v = merge.merge(cfg, **QUIET)
    assert {x["job"]: x["verdict"] for x in v} == {i: ("red" if i == "job-0004" else "merged") for i in ids}
    assert [x["job"] for x in v] == ids                                  # oldest first
    assert tree(app) >= {f"src/{i}.txt" for i in ids if i != "job-0004"} and "src/job-0004.txt" not in tree(app)
    assert jobs.get(cfg, "job-0004")["merge_refused"] == "red"
    assert all(jobs.get(cfg, i).get("merged") for i in ids if i != "job-0004")
    assert git(app, "rev-parse", "integration") != before
    assert log.read_text().count("pass") < 6 + 3      # fewer gate passes than the serial 6 + a retry each would need
    assert merge.merge(cfg, **QUIET) == []            # the bounced job is not retried; nothing else is waiting


def test_merge_batch_one_is_one_at_a_time(tmp_path):
    make_repo(tmp_path / "app")
    (tmp_path / "office").mkdir()
    log = tmp_path / "gates.log"
    cfg = setup_mode.apply(answers(tmp_path, checks=[f"echo pass >> {log}"]), tmp_path / "ws", git_init=False)
    cfg.data["stores"]["app"]["merge_batch"] = 1
    make_done_jobs(cfg, 3)
    v = merge.merge(cfg, **QUIET)
    assert [x["verdict"] for x in v] == ["merged"] * 3 and log.read_text().count("pass") == 3
