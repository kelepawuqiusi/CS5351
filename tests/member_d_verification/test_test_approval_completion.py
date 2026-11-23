"""Regression coverage for approval lifecycle and trusted completion events."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci/check_test_approval.py"
HEAD = "a" * 40
BASE = "b" * 40


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location("approval_completion_regression", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def completion(gate, tmp_path, monkeypatch):
    policy_file = tmp_path / "docs/code-governance/test-approval-policy.yaml"
    policy_file.parent.mkdir(parents=True)
    source = SCRIPT.parents[2] / "docs/code-governance/test-approval-policy.yaml"
    text = source.read_text()
    policy_file.write_text(text)
    policy = replace(gate.load_policy(text), roster_confirmed=True, approvers={
        "reviewer": {"github_login": "reviewer", "name": "Reviewer", "role": "C"},
    })
    monkeypatch.setattr(gate, "load_policy", lambda _text: policy)
    comment = gate.Comment("100", "https://example.test/100", "reviewer",
                           f"/approve-tests {HEAD}", "2026-11-23T00:00:00Z", 12)
    run = gate.WorkflowRun("9", policy.trusted_workflow, "issue_comment", "success",
                           "gate-comment-100", "reviewer")
    plan = {"feature_id": "sample", "requirements": ["REQ-1"],
            "implementation_paths": ["tradingagents/feature.py"]}
    record = gate.build_record(policy, "docs/verification/plans/sample.md", plan,
                               "c" * 64, [{"path": "tests/test_sample.py", "sha256": "d" * 64}], comment, run)
    receipt = gate.dump_record(record)
    raw = {"id": 9, "path": policy.trusted_workflow, "event": "issue_comment",
           "status": "completed", "conclusion": "success", "display_title": "gate-comment-100",
           "actor": {"login": "reviewer"}, "repository": {"full_name": "team/repo"}}
    context = {"repository": "team/repo", "workflow_run_id": "9", "pull_request": 12,
               "head_sha": HEAD, "check_run_id": "17"}
    published = []
    monkeypatch.setattr(gate, "github_pages", lambda *_a, **_k: [{"name": "record-approval", "conclusion": "success"}])
    monkeypatch.setattr(gate, "completed_context", lambda *_a: context)
    monkeypatch.setattr(gate, "github_json", lambda *_a, **_k: {
        "head_sha": HEAD, "name": "test approval", "external_id": "test-approval:9",
    })
    monkeypatch.setattr(gate, "download_receipt", lambda *_a: receipt)
    monkeypatch.setattr(gate, "pull_from_api", lambda *_a: (BASE, HEAD, "owner"))
    monkeypatch.setattr(gate, "fetch_commit", lambda *_a: None)
    monkeypatch.setattr(gate, "fetch_pull_head", lambda *_a: None)
    monkeypatch.setattr(gate, "load_github_evidence", lambda *_a: gate.Evidence((comment,), ()))
    monkeypatch.setattr(gate, "assess", lambda _r, _p, _b, h, *_a: gate.Result("passed", h, ("validated",)))

    def publish(_repo, _token, head, result, check_run_id="", conclusion=""):
        published.append((head, result.status, check_run_id, conclusion))
        return check_run_id

    monkeypatch.setattr(gate, "publish_check", publish)
    return SimpleNamespace(repo=tmp_path, raw=raw, context=context, receipt=receipt,
                           published=published, comment=comment)


def finish(gate, state):
    return gate.finish_completed_run(state.repo, "team/repo", "synthetic-token", state.raw)


def test_success_requires_completed_producer_and_current_validation(gate, completion):
    assert finish(gate, completion).status == "passed"
    assert completion.published == [(HEAD, "passed", "17", "")]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_failed_or_cancelled_producer_never_publishes_success(gate, completion, conclusion):
    completion.raw["conclusion"] = conclusion
    assert finish(gate, completion).status == "failed"
    assert all(row[1] == "failed" for row in completion.published)


@pytest.mark.parametrize("field,value", [("status", "in_progress"), ("path", ".github/workflows/other.yml")])
def test_unfinished_or_wrong_workflow_is_rejected(gate, completion, field, value):
    completion.raw[field] = value
    with pytest.raises(RuntimeError):
        finish(gate, completion)
    assert not completion.published


def test_foreign_repository_is_rejected(gate, completion):
    completion.raw["repository"] = {"full_name": "other/repo"}
    with pytest.raises(RuntimeError):
        finish(gate, completion)
    assert not completion.published


@pytest.mark.parametrize("receipt", ["", 'kind: "unexpected"\n'])
def test_absent_or_malformed_receipt_fails_closed(gate, completion, monkeypatch, receipt):
    monkeypatch.setattr(gate, "download_receipt", lambda *_a: receipt)
    assert finish(gate, completion).status == "failed"


def test_failed_validation_is_not_overridden_by_successful_producer(gate, completion, monkeypatch):
    monkeypatch.setattr(gate, "assess", lambda *_a: gate.Result("failed", HEAD, ("comment deleted",)))
    assert finish(gate, completion).status == "failed"
    assert completion.published[0][1] == "failed"


def test_changed_pr_head_is_revalidated_and_original_check_closed(gate, completion, monkeypatch):
    latest = "e" * 40
    monkeypatch.setattr(gate, "pull_from_api", lambda *_a: (BASE, latest, "owner"))
    result = finish(gate, completion)
    assert result.head == latest
    assert completion.published == [(HEAD, "failed", "17", "failure"), (latest, "passed", "", "")]


def test_evidence_api_failure_cannot_leave_final_success(gate, completion, monkeypatch):
    def fail(*_args):
        raise RuntimeError("synthetic API failure")

    monkeypatch.setattr(gate, "load_github_evidence", fail)
    with pytest.raises(RuntimeError):
        finish(gate, completion)
    assert completion.published == [(HEAD, "failed", "17", "failure")]


def test_context_must_match_the_original_open_check(gate, completion):
    completion.context["workflow_run_id"] = "8"
    with pytest.raises(RuntimeError):
        finish(gate, completion)
    assert not completion.published


def test_current_completed_receipt_is_used_even_if_list_endpoint_lags(gate, completion, monkeypatch):
    def assess(_repo, _policy, _base, head, _number, _author, evidence):
        assert len(evidence.runs) == 1
        assert gate.accepted_receipt(_policy, evidence.runs[0]) is not None
        return gate.Result("passed", head, ())

    monkeypatch.setattr(gate, "assess", assess)
    assert finish(gate, completion).status == "passed"


def test_comment_rechecks_are_not_receipt_producers(gate, completion, monkeypatch):
    monkeypatch.setattr(gate, "github_pages", lambda *_a, **_k: [{"name": "record-approval", "conclusion": "skipped"}])
    assert finish(gate, completion) is None
    assert not completion.published


def test_producer_finalize_never_publishes_a_green_check(gate, completion, monkeypatch):
    path = completion.repo / "approval.yaml"
    path.write_text(completion.receipt)
    monkeypatch.chdir(completion.repo)
    monkeypatch.setenv("RECEIPT_PATH", str(path))
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setattr(gate, "event_payload", lambda: {"comment": {"id": 100, "user": {"login": "reviewer"}}})
    assert gate.run_finalize("") == 0
    assert not completion.published


def test_producer_finalize_rejects_missing_receipt(gate, monkeypatch):
    monkeypatch.delenv("RECEIPT_PATH", raising=False)
    with pytest.raises(RuntimeError):
        gate.run_finalize("")


def test_complete_run_command_is_available(gate, monkeypatch):
    monkeypatch.setattr(gate, "run_complete_from_env", lambda: 0)
    assert gate.main(["complete-run"]) == 0


def test_self_test_does_not_depend_on_real_approver_names(gate, tmp_path, monkeypatch, capsys):
    source = SCRIPT.parents[2] / "docs/code-governance/test-approval-policy.yaml"
    text = source.read_text().replace("roster_confirmed: false", "roster_confirmed: true")
    text = text.replace("approvers: []", 'approvers:\n  - github_login: "different-person"\n    name: "Different Person"\n    role: "B"')
    policy = tmp_path / "docs/code-governance/test-approval-policy.yaml"
    policy.parent.mkdir(parents=True)
    policy.write_text(text)
    monkeypatch.setattr(gate, "repo_root_from_script", lambda: tmp_path)
    assert gate.self_test() == 0, capsys.readouterr().out


def test_github_workflow_path_ref_suffix_is_supported(gate, completion):
    completion.raw["path"] += "@main"
    assert finish(gate, completion).status == "passed"


def test_check_update_cannot_move_success_to_another_commit(gate, monkeypatch):
    calls = []

    def api(_url, _token, method="GET", payload=None):
        calls.append((method, payload))
        return {"head_sha": BASE, "name": "test approval"}

    monkeypatch.setattr(gate, "github_json", api)
    with pytest.raises(RuntimeError):
        gate.publish_check("team/repo", "synthetic-token", HEAD, gate.Result("passed", HEAD, ()), "17")
    assert len(calls) == 1


def test_check_update_payload_keeps_existing_commit_binding(gate, monkeypatch):
    calls = []

    def api(_url, _token, method="GET", payload=None):
        calls.append((method, payload))
        return {"head_sha": HEAD, "name": "test approval"}

    monkeypatch.setattr(gate, "github_json", api)
    gate.publish_check("team/repo", "synthetic-token", HEAD, gate.Result("passed", HEAD, ()), "17")
    assert [method for method, _payload in calls] == ["GET", "PATCH"]
    assert "head_sha" not in calls[1][1]


def test_ordinary_root_documents_have_exact_exemptions(gate):
    policy = gate.load_policy((SCRIPT.parents[2] / "docs/code-governance/test-approval-policy.yaml").read_text())
    for path in ["README.md", "CHANGELOG.md", "LICENSE"]:
        assert gate.classify(path, policy) == "not_applicable"
    assert gate.classify("README.md.py", policy) == "unknown"
    assert gate.classify("scripts/README.md", policy) == "test"
