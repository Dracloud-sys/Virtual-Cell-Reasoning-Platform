"""One run, end to end against a real remote, and the ways the chain between its steps breaks.

Each step passing on its own says nothing about whether the run is one run. The third review
round was about that gap; the fourth was about the two places where the chain still ended in a
string the caller supplied rather than a fact the remote reported:

* `finalize` compared a `--pushed-sha` the caller computed with `git rev-parse HEAD`, which is
  true whether or not the push happened, so a run whose push failed could still finish;
* `postflight --base` let the step that judges the diff choose how much of the diff to look at,
  and `HEAD~1` on a resumed branch hides every commit but the last.

So the fixtures here are a bare repository and a clone of it. The push is a real push, the base
is read off the real remote, and the failure paths — no push, a different commit, the right
commit on the wrong branch — are driven rather than described.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from automation.outcomes import EXIT_CODES, Status
from automation.runner import main
from workspace import Workspace

WORK_ID = "vcrp-ops-002"
BRANCH = f"claude/{WORK_ID}-gate"
SPEC = (Path(__file__).parent / "fixtures" / "complete_spec.md").read_text(encoding="utf-8")
#: A head SHA for a pull request that only exists in a payload. Full 40 characters, because a
#: prefix is not an identity and the approval parser refuses one.
PR_HEAD = "1b716d75d6c0c60eac8930018d75ee184ad36a47"


def _issue(body: str | None = None) -> dict:
    return {
        "number": 21,
        "title": f"[{WORK_ID}] gate",
        "body": body or SPEC.format(work_id=WORK_ID),
        "state": "OPEN",
        "labels": ["claude-ready"],
    }


def _passes(workdir: Path, base: str, unchanged) -> tuple[int, str]:
    return 0, "All checks passed."


def _draft_pr(head_sha: str, **overrides) -> dict:
    """The deliverable as GitHub reports it: one open draft, bound branch, targeting main."""
    pull = {
        "number": 42,
        "state": "open",
        "draft": True,
        "title": f"[{WORK_ID}] gate",
        "head": {"ref": BRANCH, "sha": head_sha},
        "base": {"ref": "main"},
    }
    pull.update(overrides)
    return pull


class _Chain:
    """The four files a run carries between its steps, and the workspace it acts on."""

    def __init__(self, tmp_path: Path, workspace: Workspace) -> None:
        self.ws = workspace
        self.locks = tmp_path / "locks"
        self.token = tmp_path / "lock.json"
        self.confirmation = tmp_path / "confirmation.json"
        self.marker = tmp_path / "proceeded.json"
        self.tmp = tmp_path

    def request(self, name: str, *, fresh: bool = False, **extra) -> Path:
        payload: dict = {
            "work_id": WORK_ID,
            "workdir": str(self.ws.root),
            "target": {
                "remote": str(self.ws.remote),
                "branch": BRANCH,
                "base_branch": "main",
            },
            "queue_pages": [
                {"issues": [_issue()], "pageInfo": {"hasNextPage": False}, "totalCount": 1}
            ],
            "lock": {"kind": "file", "directory": str(self.locks)},
        }
        if fresh:
            payload["captured_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        for key, value in extra.items():
            if key == "target":
                payload["target"] = {**payload["target"], **value}
            else:
                payload[key] = value
        path = self.tmp / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def phase1(self, **extra) -> Path:
        return self.request("p1.json", **extra)

    def phase2(self, **extra) -> Path:
        return self.request("p2.json", fresh=True, **extra)

    def preflight(self, request: Path | None = None) -> int:
        return main(
            [
                "preflight",
                "--request",
                str(request or self.phase1()),
                "--token",
                str(self.token),
                "--development",
            ]
        )

    def confirm(self, request: Path | None = None) -> int:
        return main(
            [
                "confirm",
                "--request",
                str(request or self.phase2()),
                "--token",
                str(self.token),
                "--confirmation",
                str(self.confirmation),
                "--proceed-marker",
                str(self.marker),
                "--development",
            ]
        )

    def postflight(self, request: Path | None = None, *, base: str = "") -> int:
        argv = [
            "postflight",
            "--request",
            str(request or self.phase2()),
            "--token",
            str(self.token),
            "--confirmation",
            str(self.confirmation),
            "--development",
        ]
        if base:
            argv += ["--base", base]
        return main(argv)

    def completion(
        self, *, pulls: list[dict] | None = None, captured_at: str | None = None
    ) -> Path:
        """The pull request listing, re-queried after the push. Correct unless a test breaks it."""
        payload = {
            "captured_at": captured_at or datetime.now(UTC).isoformat(timespec="seconds"),
            "pull_requests": [_draft_pr(self.verified_head())] if pulls is None else pulls,
        }
        path = self.tmp / "completion.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def finalize(
        self,
        request: Path | None = None,
        *,
        pushed: str = "",
        pulls: list[dict] | None = None,
        completion: Path | None = None,
    ) -> int:
        argv = [
            "finalize",
            "--request",
            str(request or self.phase1()),
            "--token",
            str(self.token),
            "--confirmation",
            str(self.confirmation),
            "--completion",
            str(completion or self.completion(pulls=pulls)),
            "--development",
        ]
        if pushed:
            argv += ["--pushed-sha", pushed]
        return main(argv)

    # --- the work itself ----------------------------------------------------------------------

    def work(self, value: str = "2") -> str:
        self.ws.branch(BRANCH)
        self.ws.write("scripts/automation/gate.py", f"x = {value}\n")
        return self.ws.commit()

    def out_of_scope(self, value: str = "9") -> str:
        self.ws.branch(BRANCH)
        self.ws.write("src/virtualcell/cli.py", f"z = {value}\n")
        return self.ws.commit("out of scope")

    def verified_head(self) -> str:
        return json.loads(self.confirmation.read_text())["verified_head"]


@pytest.fixture
def chain(tmp_path: Path, workspace: Workspace, monkeypatch) -> _Chain:
    monkeypatch.setattr("automation.postflight.run_verify", _passes)
    return _Chain(tmp_path, workspace)


# --- the run that works -----------------------------------------------------------------------


def test_the_whole_chain_runs_and_gives_the_lock_back(chain: _Chain) -> None:
    assert chain.preflight() == 0
    assert chain.token.exists()
    assert not chain.marker.exists()  # taking the lock is not permission to work

    assert chain.confirm() == 0
    assert chain.marker.exists()
    assert chain.confirmation.exists()

    head = chain.work()
    assert chain.postflight() == 0
    assert chain.verified_head() == head

    chain.ws.push(BRANCH)
    assert chain.finalize() == 0
    assert chain.ws.remote_head(BRANCH) == head
    assert not chain.token.exists()
    assert not chain.confirmation.exists()
    assert chain.preflight() == 0  # and the next run can start


def test_the_base_comes_from_the_remote_and_is_pinned_as_a_full_sha(chain: _Chain) -> None:
    assert chain.preflight() == 0

    target = json.loads(chain.token.read_text())["target"]

    assert target["base_sha"] == chain.ws.base_sha
    assert len(target["base_sha"]) == 40
    assert target["branch"] == BRANCH


# --- the push, as the remote reports it -------------------------------------------------------


def test_a_run_that_never_pushed_cannot_finalize(chain: _Chain) -> None:
    """The failure the old `--pushed-sha` comparison could not see: local HEAD, no push."""
    chain.preflight()
    chain.confirm()
    head = chain.work()
    assert chain.postflight() == 0

    code = chain.finalize(pushed=head)  # the caller's own rev-parse, and it is not enough

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.ws.remote_head(BRANCH) == ""
    assert chain.token.exists()  # the run is unfinished, so it keeps what it needs to retry
    assert chain.confirmation.exists()


def test_a_branch_carrying_a_different_commit_is_refused(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    verified = chain.work()
    chain.postflight()
    chain.ws.write("scripts/automation/gate.py", "x = 99\n")
    later = chain.ws.commit("something else")
    chain.ws.push(BRANCH)

    code = chain.finalize()

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.ws.remote_head(BRANCH) == later != verified


def test_the_verified_commit_on_some_other_branch_is_not_this_run_finishing(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    head = chain.work()
    chain.postflight()
    chain.ws.push("claude/somewhere-else")

    code = chain.finalize()

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.ws.remote_head("claude/somewhere-else") == head
    assert chain.ws.remote_head(BRANCH) == ""


def test_a_pushed_sha_the_remote_contradicts_is_refused(chain: _Chain) -> None:
    """`--pushed-sha` survives only as a claim, and the remote is allowed to disagree with it."""
    chain.preflight()
    chain.confirm()
    chain.work()
    chain.postflight()
    chain.ws.push(BRANCH)

    assert chain.finalize(pushed="0" * 40) == EXIT_CODES[Status.BLOCKED_SCOPE]


# --- the deliverable: a draft pull request, not just a pushed branch --------------------------


def _pushed(chain: _Chain) -> str:
    """Run the chain as far as a verified, pushed branch, and return the verified head."""
    chain.preflight()
    chain.confirm()
    head = chain.work()
    assert chain.postflight() == 0
    chain.ws.push(BRANCH)
    return head


def test_a_pushed_branch_with_no_pull_request_is_not_a_finished_run(chain: _Chain) -> None:
    """The Routine's output is a draft PR; a branch nobody was asked to look at is not it."""
    _pushed(chain)

    code = chain.finalize(pulls=[])

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.token.exists()  # the run is unfinished: it can open the PR and retry
    assert chain.confirmation.exists()


def test_a_pull_request_that_is_not_a_draft_does_not_complete_the_run(chain: _Chain) -> None:
    head = _pushed(chain)

    code = chain.finalize(pulls=[_draft_pr(head, draft=False)])

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.token.exists()


def test_a_pull_request_targeting_something_other_than_main_is_refused(chain: _Chain) -> None:
    head = _pushed(chain)

    code = chain.finalize(pulls=[_draft_pr(head, base={"ref": "some-other-branch"})])

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]


def test_a_pull_request_at_a_different_commit_is_refused(chain: _Chain) -> None:
    _pushed(chain)

    code = chain.finalize(pulls=[_draft_pr("0" * 40)])

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]


def test_a_pull_request_from_another_branch_for_this_work_is_refused(chain: _Chain) -> None:
    """Same work id, different branch: the reviewer is reading somewhere the work did not land."""
    head = _pushed(chain)

    code = chain.finalize(
        pulls=[_draft_pr(head, head={"ref": f"claude/{WORK_ID}-elsewhere", "sha": head})]
    )

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]


def test_two_open_pull_requests_for_one_work_item_are_not_a_choice(chain: _Chain) -> None:
    head = _pushed(chain)

    code = chain.finalize(pulls=[_draft_pr(head), _draft_pr(head, number=43)])

    assert code == EXIT_CODES[Status.AMBIGUOUS_PULL_REQUEST]


def test_a_listing_that_does_not_say_whether_a_pull_request_is_a_draft_is_refused(
    chain: _Chain,
) -> None:
    """Both guesses are wrong: assume true and a ready PR completes, assume false and none does."""
    head = _pushed(chain)
    payload = _draft_pr(head)
    payload.pop("draft")

    code = chain.finalize(pulls=[payload])

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]


def test_completion_evidence_from_before_the_lock_is_refused(chain: _Chain) -> None:
    _pushed(chain)
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="seconds")

    code = chain.finalize(completion=chain.completion(captured_at=stale))

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]


def test_a_completion_refusal_leaves_the_lock_held_and_the_revision_unrecorded(
    chain: _Chain,
) -> None:
    """Unlike a scope violation, this run is not over: the PR can be opened and finalize retried."""
    extras = _revision_request(chain)
    chain.preflight(chain.phase1(**extras))
    chain.confirm(chain.phase2(**extras))
    chain.work()
    chain.postflight(chain.phase2(**extras))
    chain.ws.push(BRANCH)

    refused = chain.finalize(chain.phase1(**extras), pulls=[])
    retried = chain.finalize(chain.phase1(**extras))

    assert refused == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert retried == 0
    assert "rev-1" in _applied_ids(chain)


def test_a_revision_recorded_against_the_wrong_pull_request_is_refused(chain: _Chain) -> None:
    """The bound instruction was written on #42; retiring it against #43 retires it falsely."""
    extras = _revision_request(chain)
    chain.preflight(chain.phase1(**extras))
    chain.confirm(chain.phase2(**extras))
    head = chain.work()
    chain.postflight(chain.phase2(**extras))
    chain.ws.push(BRANCH)

    code = chain.finalize(chain.phase1(**extras), pulls=[_draft_pr(head, number=43)])

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert _applied(chain) == ""


# --- the base, as phase one froze it ----------------------------------------------------------


def test_the_whole_branch_is_measured_not_just_its_last_commit(chain: _Chain, capsys) -> None:
    """Two commits, the scope violation in the *first*. Measuring from HEAD~1 would miss it."""
    chain.preflight()
    chain.confirm()
    chain.out_of_scope()
    chain.work()
    capsys.readouterr()

    code = chain.postflight()

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert "src/virtualcell/cli.py" in capsys.readouterr().out


def test_a_base_that_disagrees_with_the_token_is_refused(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    chain.out_of_scope()
    chain.work()

    code = chain.postflight(base="HEAD~1")

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.preflight() == 0  # and the lock came back


def test_a_request_naming_a_different_branch_after_phase_one_is_refused(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    chain.work()

    code = chain.postflight(chain.phase2(target={"branch": f"claude/{WORK_ID}-elsewhere"}))

    assert code == EXIT_CODES[Status.BLOCKED_SCOPE]


# --- the lock configuration, which has no default ---------------------------------------------


def test_a_missing_lock_configuration_does_not_fall_back_to_memory(chain: _Chain) -> None:
    """A memory lock is not a weaker lock. It is no lock, and it reports success either way."""
    request = chain.phase1()
    payload = json.loads(request.read_text())
    payload.pop("lock")
    request.write_text(json.dumps(payload), encoding="utf-8")

    assert chain.preflight(request) == EXIT_CODES[Status.INVALID_SPEC]
    assert not chain.token.exists()


def test_a_misspelled_lock_kind_is_refused_rather_than_ignored(chain: _Chain) -> None:
    request = chain.phase1(lock={"kind": "git_ref", "remote": str(chain.ws.remote)})

    assert chain.preflight(request) == EXIT_CODES[Status.INVALID_SPEC]


def test_the_whole_test_request_is_refused_without_the_development_flag(
    chain: _Chain, capsys
) -> None:
    """Everything in this file points at a temporary bare repo. Production says where it goes."""
    code = main(["preflight", "--request", str(chain.phase1()), "--token", str(chain.token)])

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    assert "run_target.json" in capsys.readouterr().out
    assert not chain.token.exists()


def test_a_git_ref_lock_is_taken_and_given_back(chain: _Chain) -> None:
    """The production kind, exercised against the bare remote the development flag allows."""
    request = chain.phase1(
        lock={"kind": "git-ref", "remote": str(chain.ws.remote), "workdir": str(chain.ws.root)}
    )

    assert chain.preflight(request) == 0
    assert chain.ws.git("ls-remote", str(chain.ws.remote), f"refs/vcrp-locks/{WORK_ID}") != ""
    assert (
        main(
            [
                "release",
                "--request",
                str(request),
                "--token",
                str(chain.token),
                "--development",
            ]
        )
        == 0
    )
    assert chain.ws.git("ls-remote", str(chain.ws.remote), f"refs/vcrp-locks/{WORK_ID}") == ""


# --- releasing, and failing to ---------------------------------------------------------------


def test_a_base_branch_the_remote_does_not_have_gives_the_lock_back(chain: _Chain) -> None:
    code = chain.preflight(chain.phase1(target={"base_branch": "no-such-branch"}))

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert chain.preflight() == 0  # the lock was handed back


def test_a_release_that_fails_on_the_way_out_of_preflight_is_reported(
    chain: _Chain, monkeypatch, capsys
) -> None:
    """It used to be dropped: the refusal was printed and the lock quietly stayed on the remote."""
    monkeypatch.setattr("automation.locking.FileLockStore.release", lambda *a, **k: False)

    code = chain.preflight(chain.phase1(target={"base_branch": "no-such-branch"}))
    printed = capsys.readouterr().out

    assert code == EXIT_CODES[Status.BLOCKED_GITHUB_ACCESS]
    assert "no-such-branch" in printed
    assert "the lock may be stuck" in printed
    assert "force-with-lease" in printed


def test_a_release_that_fails_is_not_a_finished_run(chain: _Chain, monkeypatch) -> None:
    """Exit 0 with the lock still held strands every later run on ALREADY_RUNNING."""
    chain.preflight()
    chain.confirm()
    chain.work()
    chain.postflight()
    chain.ws.push(BRANCH)
    monkeypatch.setattr("automation.runner._release", lambda store, token: False)

    code = chain.finalize()

    assert code != 0
    assert chain.token.exists()  # kept, so `release` can retry
    assert chain.confirmation.exists()


def test_finalize_can_be_retried_after_a_release_that_failed(chain: _Chain, monkeypatch) -> None:
    chain.preflight()
    chain.confirm()
    chain.work()
    chain.postflight()
    chain.ws.push(BRANCH)
    monkeypatch.setattr("automation.runner._release", lambda store, token: False)
    assert chain.finalize() != 0
    monkeypatch.undo()

    assert chain.finalize() == 0
    assert not chain.token.exists()
    assert chain.preflight() == 0


# --- the revision, recorded only once the remote has the work --------------------------------


def _revision_request(chain: _Chain, **extra) -> dict:
    return {
        "pull_requests": [
            {
                "number": 42,
                "state": "open",
                "title": "t",
                "head": {"ref": BRANCH, "sha": PR_HEAD},
            }
        ],
        "approvals": [
            {
                "id": "rev-1",
                "user": {"login": "Dracloud-sys"},
                "body": "please narrow the parser",
                "commit_id": PR_HEAD,
                "pull_request_number": 42,
                "state": "APPROVED",
            }
        ],
        "state": {
            "kind": "git-ref",
            "remote": str(chain.ws.remote),
            "workdir": str(chain.ws.root),
        },
        **extra,
    }


def _applied(chain: _Chain) -> str:
    """What the durable state ref points at on the remote, or "" when it does not exist."""
    return chain.ws.git("ls-remote", str(chain.ws.remote), "refs/vcrp-state/applied-revisions")


def _applied_ids(chain: _Chain) -> str:
    chain.ws.git("fetch", "-q", str(chain.ws.remote), "refs/vcrp-state/applied-revisions")
    return chain.ws.git("show", "FETCH_HEAD:applied.json")


def test_the_revision_is_recorded_only_after_the_remote_carries_the_work(chain: _Chain) -> None:
    extras = _revision_request(chain)
    assert chain.preflight(chain.phase1(**extras)) == 0
    assert chain.confirm(chain.phase2(**extras)) == 0
    chain.work()
    assert chain.postflight(chain.phase2(**extras)) == 0

    before = _applied(chain)
    chain.ws.push(BRANCH)
    assert chain.finalize(chain.phase1(**extras)) == 0

    assert before == ""
    assert "rev-1" in _applied_ids(chain)


def test_an_unpushed_revision_is_never_recorded(chain: _Chain) -> None:
    extras = _revision_request(chain)
    chain.preflight(chain.phase1(**extras))
    chain.confirm(chain.phase2(**extras))
    chain.work()
    chain.postflight(chain.phase2(**extras))

    assert chain.finalize(chain.phase1(**extras)) == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert _applied(chain) == ""


def test_a_revision_with_nowhere_to_record_it_stops_before_the_lock(chain: _Chain) -> None:
    """Found at phase one, not after the push, because the second time is a repeat of the work."""
    extras = _revision_request(chain)
    extras.pop("state")

    code = chain.preflight(chain.phase1(**extras))

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    assert not chain.token.exists()


def test_a_request_may_not_declare_what_has_already_been_applied(chain: _Chain, capsys) -> None:
    """Otherwise the agent decides whether the revision it is about to apply was already done."""
    extras = _revision_request(chain)
    extras.pop("state")
    extras["applied_revision_ids"] = ["rev-1"]

    code = chain.preflight(chain.phase1(**extras))

    assert code == EXIT_CODES[Status.INVALID_SPEC]
    assert "which revisions have already been applied" in capsys.readouterr().out


# --- the chain, broken in each of the places the third round named ---------------------------


def test_widening_the_allowed_paths_after_phase_one_does_not_widen_the_diff(chain: _Chain) -> None:
    """The policy comes from a body matching the confirmed hash, not from the request file."""
    chain.preflight()
    chain.confirm()
    chain.out_of_scope()

    widened = SPEC.format(work_id=WORK_ID).replace(
        "scripts/automation/\ntests/automation/", "scripts/\ntests/\nsrc/"
    )
    tampered = chain.phase2(
        queue_pages=[
            {"issues": [_issue(widened)], "pageInfo": {"hasNextPage": False}, "totalCount": 1}
        ]
    )

    assert chain.postflight(tampered) == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.preflight() == 0  # and the lock came back


def test_an_out_of_scope_change_stops_the_push_and_frees_the_lock(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    chain.out_of_scope()

    assert chain.postflight() == EXIT_CODES[Status.BLOCKED_SCOPE]
    assert chain.preflight() == 0


def test_postflight_refuses_once_the_lock_has_changed_hands(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    chain.work()
    next(chain.locks.iterdir()).write_text("someone-else now nonce\n", encoding="utf-8")

    assert chain.postflight() == EXIT_CODES[Status.ALREADY_RUNNING]


def test_finalize_refuses_once_the_lock_has_changed_hands(chain: _Chain) -> None:
    chain.preflight()
    chain.confirm()
    chain.work()
    chain.postflight()
    chain.ws.push(BRANCH)
    next(chain.locks.iterdir()).write_text("someone-else now nonce\n", encoding="utf-8")

    assert chain.finalize() == EXIT_CODES[Status.ALREADY_RUNNING]


def test_a_branch_that_appeared_after_the_lock_stops_the_run(chain: _Chain) -> None:
    """Another run may be part way through this work; a second branch would fork it."""
    chain.preflight()

    code = chain.confirm(chain.phase2(existing_branches=[f"claude/{WORK_ID}-someone-else"]))

    assert code == EXIT_CODES[Status.AWAITING_REVIEW]
    assert chain.preflight() == 0  # lock returned


def test_confirming_without_first_locking_is_refused(chain: _Chain) -> None:
    assert chain.confirm() == EXIT_CODES[Status.ALREADY_RUNNING]
    assert not chain.marker.exists()


def test_a_restarted_process_can_still_release(chain: _Chain) -> None:
    """The token is on disk, so the process that releases need not be the one that took it."""
    chain.preflight()

    finished = subprocess.run(
        [
            "python3",
            str(Path(__file__).resolve().parents[2] / "scripts" / "automation" / "cli.py"),
            "release",
            "--request",
            str(chain.phase1()),
            "--token",
            str(chain.token),
            "--development",
        ],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr
    assert chain.preflight() == 0
