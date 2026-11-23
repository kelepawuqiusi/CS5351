#!/usr/bin/env python3
"""Check that feature work was test-approved before implementation.

The policy and this script must be taken from the protected baseline. A pull
request's copy is not the source of approvers or rules. This program only reads
git objects and GitHub events. It does not execute pull request code or install
pull request dependencies.

A YAML approval file is not itself an approval. The approval is an authorized
member's `/approve-tests <full SHA>` comment accepted by the trusted workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
APPROVAL_ID = re.compile(r"^ta-[0-9a-f]{12}-[0-9]+$")
GOVERNANCE_ID = re.compile(r"^tg-[0-9a-f]{12}-[0-9]+$")
CASE_KINDS = ("normal", "boundary", "error", "security")


@dataclass(frozen=True)
class Policy:
    roster_confirmed: bool
    approvers: dict[str, dict[str, str]]
    implementation_prefixes: tuple[str, ...]
    implementation_files: frozenset[str]
    test_prefixes: tuple[str, ...]
    governance_prefixes: tuple[str, ...]
    governance_files: frozenset[str]
    not_applicable_prefixes: tuple[str, ...]
    not_applicable_suffixes: frozenset[str]
    not_applicable_files: frozenset[str]
    plan_prefix: str
    approval_prefix: str
    trusted_workflow: str
    approve_command: str
    revoke_command: str
    governance_roster_confirmed: bool
    governance_reviewers: dict[str, dict[str, str]]
    governance_command: str


@dataclass(frozen=True)
class Comment:
    comment_id: str
    url: str
    user: str
    body: str
    created_at: str
    pull_request: int


@dataclass(frozen=True)
class WorkflowRun:
    run_id: str
    path: str
    event: str
    conclusion: str
    display_title: str
    actor: str
    receipt: str = ""


@dataclass(frozen=True)
class Evidence:
    comments: tuple[Comment, ...] = ()
    runs: tuple[WorkflowRun, ...] = ()


@dataclass(frozen=True)
class Result:
    status: str
    head: str
    lines: tuple[str, ...]

    def text(self) -> str:
        first = f"test approval: {self.status} for {self.head}"
        return "\n".join((first, *self.lines))

    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


def scalar(token: str):
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    if token == "true":
        return True
    if token == "false":
        return False
    if token in {"null", "~"}:
        return None
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token


def split_key(text: str) -> tuple[str, str]:
    quote = ""
    for index, char in enumerate(text):
        if char in {'"', "'"}:
            quote = "" if quote == char else (quote or char)
            continue
        if char == ":" and not quote:
            return text[:index].strip(), text[index + 1 :].strip()
    raise ValueError(f"expected 'key: value' in {text!r}")


def meaningful_lines(text: str) -> list[tuple[int, str]]:
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw:
            raise ValueError("gate YAML cannot contain tabs")
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, stripped))
    return lines


def parse_block(lines: list[tuple[int, str]], index: int, indent: int):
    if index >= len(lines) or lines[index][0] < indent:
        return {}, index
    if lines[index][1].startswith("- "):
        return parse_list(lines, index, indent)
    return parse_map(lines, index, indent)


def parse_map(lines: list[tuple[int, str]], index: int, indent: int):
    result: dict = {}
    while index < len(lines):
        level, text = lines[index]
        if level < indent or text.startswith("- "):
            break
        if level != indent:
            raise ValueError(f"unexpected indent in {text!r}")
        key, rest = split_key(text)
        if key in result:
            raise ValueError(f"duplicate key {key}")
        index += 1
        if rest == "":
            value, index = parse_block(lines, index, indent + 2)
        elif rest == "[]":
            value = []
        elif rest == "{}":
            value = {}
        else:
            value = scalar(rest)
        result[key] = value
    return result, index


def parse_list(lines: list[tuple[int, str]], index: int, indent: int):
    items = []
    while index < len(lines):
        level, text = lines[index]
        if level != indent or not text.startswith("- "):
            break
        payload = text[2:].strip()
        index += 1
        if payload == "":
            value, index = parse_block(lines, index, indent + 2)
            items.append(value)
            continue
        if ":" in payload:
            key, rest = split_key(payload)
            item: dict = {}
            if rest == "":
                nested, index = parse_block(lines, index, indent + 4)
                item[key] = nested
            else:
                item[key] = scalar(rest)
            while index < len(lines):
                child_level, child_text = lines[index]
                if child_level != indent + 2 or child_text.startswith("- "):
                    break
                child_key, child_rest = split_key(child_text)
                index += 1
                if child_rest == "":
                    nested, index = parse_block(lines, index, indent + 4)
                    item[child_key] = nested
                elif child_rest == "[]":
                    item[child_key] = []
                else:
                    item[child_key] = scalar(child_rest)
            items.append(item)
            continue
        items.append(scalar(payload))
    return items, index


def parse_yaml(text: str):
    lines = meaningful_lines(text)
    if not lines:
        raise ValueError("YAML is empty")
    value, index = parse_block(lines, 0, 0)
    if index != len(lines):
        raise ValueError("YAML has trailing content")
    if not isinstance(value, dict):
        raise ValueError("YAML root must be a mapping")
    return value


def people(entries) -> dict[str, dict[str, str]]:
    found = {}
    for entry in entries or []:
        login = str(entry["github_login"])
        found[login] = {
            "github_login": login,
            "name": str(entry["name"]),
            "role": str(entry["role"]),
        }
    return found


def load_policy(text: str) -> Policy:
    data = parse_yaml(text)
    return Policy(
        roster_confirmed=bool(data.get("roster_confirmed")),
        approvers=people(data.get("approvers")),
        implementation_prefixes=tuple(data.get("implementation_prefixes") or []),
        implementation_files=frozenset(data.get("implementation_files") or []),
        test_prefixes=tuple(data.get("test_prefixes") or []),
        governance_prefixes=tuple(data.get("governance_prefixes") or []),
        governance_files=frozenset(data.get("governance_files") or []),
        not_applicable_prefixes=tuple(data.get("not_applicable_prefixes") or []),
        not_applicable_suffixes=frozenset(data.get("not_applicable_suffixes") or []),
        not_applicable_files=frozenset(data.get("not_applicable_files") or []),
        plan_prefix=str(data["plan_prefix"]),
        approval_prefix=str(data["approval_prefix"]),
        trusted_workflow=str(data["trusted_workflow"]),
        approve_command=str(data["approve_command"]),
        revoke_command=str(data["revoke_command"]),
        governance_roster_confirmed=bool(data.get("governance_roster_confirmed")),
        governance_reviewers=people(data.get("governance_reviewers")),
        governance_command=str(data.get("governance_command") or "/approve-governance"),
    )


def matches(path: str, prefixes: tuple[str, ...], files: frozenset[str]) -> bool:
    if path in files:
        return True
    return any(path.startswith(prefix) for prefix in prefixes)


def classify(path: str, policy: Policy) -> str:
    relative = path.removeprefix("./")
    if relative in {policy.plan_prefix + "README.md", policy.approval_prefix + "README.md"}:
        return "not_applicable"
    if relative.startswith(policy.plan_prefix) and relative.endswith(".md"):
        return "plan"
    name = relative.removeprefix(policy.approval_prefix)
    if relative.startswith(policy.approval_prefix) and name.endswith(".yaml") and "/" not in name:
        return "approval"
    if matches(relative, policy.governance_prefixes, policy.governance_files):
        return "governance"
    if matches(relative, policy.implementation_prefixes, policy.implementation_files):
        return "implementation"
    if matches(relative, policy.test_prefixes, frozenset()):
        return "test"
    if matches(relative, policy.not_applicable_prefixes, policy.not_applicable_files):
        return "not_applicable"
    if any(relative.endswith(suffix) for suffix in policy.not_applicable_suffixes):
        return "not_applicable"
    return "unknown"


def git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, check=False)


def git_text(repo: Path, args: list[str]) -> str:
    result = git(repo, args)
    if result.returncode != 0:
        message = result.stderr.decode() or result.stdout.decode() or "git failed"
        raise RuntimeError(message.strip())
    return result.stdout.decode()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    if not FULL_SHA.fullmatch(ancestor) or not FULL_SHA.fullmatch(descendant):
        return False
    return git(repo, ["merge-base", "--is-ancestor", ancestor, descendant]).returncode == 0


def commit_parents(repo: Path, sha: str) -> list[str]:
    line = git_text(repo, ["rev-list", "--parents", "-1", sha]).strip().split()
    return line[1:]


def parse_name_status(blob: bytes) -> list[tuple[str, str, str | None]]:
    parts = blob.decode().split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    rows: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if status[:1] in {"R", "C"}:
            old, new = parts[index], parts[index + 1]
            index += 2
            rows.append((status, new, old))
        else:
            rows.append((status, parts[index], None))
            index += 1
    return rows


def implicated(rows: list[tuple[str, str, str | None]]) -> list[str]:
    paths = []
    for _status, path, old in rows:
        paths.append(path.removeprefix("./"))
        if old:
            paths.append(old.removeprefix("./"))
    return paths


def commit_changes(repo: Path, sha: str) -> list[str]:
    paths: list[str] = []
    for parent in commit_parents(repo, sha) or ["4b825dc642cb6eb9a060e54bf8d69288fbee4904"]:
        # The empty-tree hash above is only a fallback label; skip a missing parent.
        if git(repo, ["cat-file", "-e", f"{parent}^{{commit}}"]).returncode != 0:
            continue
        result = git(repo, ["diff", "--name-status", "-z", parent, sha])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode() or "git diff failed")
        paths.extend(implicated(parse_name_status(result.stdout)))
    return paths


def pull_commits(repo: Path, base: str, head: str) -> tuple[str, list[str]]:
    merge_base = git_text(repo, ["merge-base", base, head]).strip()
    listed = git_text(repo, ["rev-list", "--reverse", f"{merge_base}..{head}"]).split()
    return merge_base, listed


def file_bytes(repo: Path, sha: str, path: str) -> bytes | None:
    result = git(repo, ["show", f"{sha}:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def front_matter(text: str) -> dict:
    if not text.startswith("---\n"):
        raise ValueError("plan is missing YAML front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("plan front matter is not closed")
    return parse_yaml(text[4:end])


def validate_plan(data: dict) -> str | None:
    required = {
        "feature_id",
        "requirements",
        "implementation_paths",
        "test_files",
        "cases",
        "pass_condition",
    }
    if set(data) != required:
        return "plan front matter is missing a required field"
    if not isinstance(data["feature_id"], str) or not data["feature_id"]:
        return "plan feature_id is empty"
    if not data["requirements"] or not all(isinstance(item, str) and item for item in data["requirements"]):
        return "plan requirements are incomplete"
    if not isinstance(data["implementation_paths"], list) or not all(
        isinstance(item, str) and item for item in data["implementation_paths"]
    ):
        return "plan implementation paths are invalid"
    if not data["test_files"] or not all(isinstance(item, str) and item for item in data["test_files"]):
        return "plan test files are incomplete"
    if not isinstance(data["pass_condition"], str) or not data["pass_condition"].strip():
        return "plan pass condition is empty"
    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        return "plan cases are incomplete"
    kinds = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "kind", "expected"}:
            return "a plan case needs id, kind, and expected"
        if not case["id"] or not case["expected"] or case["kind"] not in CASE_KINDS:
            return "a plan case is incomplete"
        kinds.add(case["kind"])
    if set(CASE_KINDS) - kinds:
        return "plan needs a normal, boundary, error, and security case"
    return None


def covers(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/") and (path.startswith(pattern) or path == pattern[:-1]):
            return True
        if path == pattern:
            return True
    return False


def command_token(policy: Policy, body: str, command: str) -> str | None:
    prefix = command + " "
    if not body.strip().startswith(prefix):
        return None
    token = body.strip()[len(prefix) :].strip()
    if not FULL_SHA.fullmatch(token):
        return None
    if body.strip() != f"{command} {token}":
        return None
    return token


def command_sha(policy: Policy, body: str) -> str | None:
    return command_token(policy, body, policy.approve_command)


def revoke_target(policy: Policy, body: str) -> str | None:
    prefix = policy.revoke_command + " "
    stripped = body.strip()
    if not stripped.startswith(prefix):
        return None
    token = stripped[len(prefix) :].strip()
    if not APPROVAL_ID.fullmatch(token) or stripped != f"{policy.revoke_command} {token}":
        return None
    return token


def governance_sha(policy: Policy, body: str) -> str | None:
    return command_token(policy, body, policy.governance_command)


def dump_record(record: dict) -> str:
    approver = record["approver"]
    plan = record["plan"]
    scope = record["scope"]
    evidence = record["evidence"]
    lines = [
        'schema_version: "1"',
        'kind: "approval"',
        f'approval_id: "{record["approval_id"]}"',
        f'feature_id: "{record["feature_id"]}"',
        f"pull_request: {record['pull_request']}",
        "approver:",
        f'  github_login: "{approver["github_login"]}"',
        f'  name: "{approver["name"]}"',
        f'  role: "{approver["role"]}"',
        f'approved_at: "{record["approved_at"]}"',
        f'approved_commit: "{record["approved_commit"]}"',
        "plan:",
        f'  path: "{plan["path"]}"',
        f'  sha256: "{plan["sha256"]}"',
        "scope:",
        "  requirements:",
    ]
    lines.extend(f'    - "{item}"' for item in scope["requirements"])
    lines.append("  implementation_paths:")
    if scope["implementation_paths"]:
        lines.extend(f'    - "{item}"' for item in scope["implementation_paths"])
    else:
        lines[-1] = "  implementation_paths: []"
    lines.append("  test_files:")
    for item in scope["test_files"]:
        lines.append(f'    - path: "{item["path"]}"')
        lines.append(f'      sha256: "{item["sha256"]}"')
    lines.extend(
        [
            "evidence:",
            f'  comment_id: "{evidence["comment_id"]}"',
            f'  comment_url: "{evidence["comment_url"]}"',
            f'  workflow_run_id: "{evidence["workflow_run_id"]}"',
            f'  comment_body: "{evidence["comment_body"]}"',
            "",
        ]
    )
    return "\n".join(lines)


def normalize_record(data: dict) -> dict:
    keys = {
        "schema_version",
        "kind",
        "approval_id",
        "feature_id",
        "pull_request",
        "approver",
        "approved_at",
        "approved_commit",
        "plan",
        "scope",
        "evidence",
    }
    if set(data) != keys or data["schema_version"] != "1" or data.get("kind") != "approval":
        raise ValueError("approval record schema does not match")
    approver = data["approver"]
    if set(approver) != {"github_login", "name", "role"}:
        raise ValueError("approver fields do not match")
    plan = data["plan"]
    if set(plan) != {"path", "sha256"}:
        raise ValueError("plan fingerprint fields do not match")
    scope = data["scope"]
    if set(scope) != {"requirements", "implementation_paths", "test_files"}:
        raise ValueError("approval scope fields do not match")
    evidence = evidence_fields(data["evidence"])
    tests = []
    for item in scope["test_files"]:
        if set(item) != {"path", "sha256"}:
            raise ValueError("test fingerprint fields do not match")
        tests.append({"path": str(item["path"]), "sha256": str(item["sha256"])})
    return {
        "schema_version": "1",
        "kind": "approval",
        "approval_id": str(data["approval_id"]),
        "feature_id": str(data["feature_id"]),
        "pull_request": int(data["pull_request"]),
        "approver": {key: str(approver[key]) for key in ("github_login", "name", "role")},
        "approved_at": str(data["approved_at"]),
        "approved_commit": str(data["approved_commit"]),
        "plan": {"path": str(plan["path"]), "sha256": str(plan["sha256"])},
        "scope": {
            "requirements": [str(item) for item in scope["requirements"]],
            "implementation_paths": [str(item) for item in scope["implementation_paths"]],
            "test_files": tests,
        },
        "evidence": evidence,
    }


def evidence_fields(evidence: dict) -> dict:
    if set(evidence) != {"comment_id", "comment_url", "workflow_run_id", "comment_body"}:
        raise ValueError("approval evidence fields do not match")
    return {key: str(evidence[key]) for key in ("comment_id", "comment_url", "workflow_run_id", "comment_body")}


def normalize_revocation(data: dict) -> dict:
    keys = {"schema_version", "kind", "approval_id", "pull_request", "github_login", "evidence"}
    if set(data) != keys or data["schema_version"] != "1" or data.get("kind") != "revocation":
        raise ValueError("revocation receipt schema does not match")
    if not APPROVAL_ID.fullmatch(str(data["approval_id"])):
        raise ValueError("revocation approval id does not match")
    return {
        "schema_version": "1",
        "kind": "revocation",
        "approval_id": str(data["approval_id"]),
        "pull_request": int(data["pull_request"]),
        "github_login": str(data["github_login"]),
        "evidence": evidence_fields(data["evidence"]),
    }


def normalize_governance(data: dict) -> dict:
    keys = {
        "schema_version",
        "kind",
        "approval_id",
        "pull_request",
        "reviewer",
        "approved_at",
        "approved_commit",
        "files",
        "evidence",
    }
    if set(data) != keys or data["schema_version"] != "1" or data.get("kind") != "governance":
        raise ValueError("governance receipt schema does not match")
    if not GOVERNANCE_ID.fullmatch(str(data["approval_id"])):
        raise ValueError("governance approval id does not match")
    reviewer = data["reviewer"]
    if set(reviewer) != {"github_login", "name", "role"}:
        raise ValueError("governance reviewer fields do not match")
    files = []
    for item in data["files"]:
        if set(item) != {"path", "sha256"}:
            raise ValueError("governance fingerprint fields do not match")
        files.append({"path": str(item["path"]), "sha256": str(item["sha256"])})
    return {
        "schema_version": "1",
        "kind": "governance",
        "approval_id": str(data["approval_id"]),
        "pull_request": int(data["pull_request"]),
        "reviewer": {key: str(reviewer[key]) for key in ("github_login", "name", "role")},
        "approved_at": str(data["approved_at"]),
        "approved_commit": str(data["approved_commit"]),
        "files": files,
        "evidence": evidence_fields(data["evidence"]),
    }


def dump_revocation(record: dict) -> str:
    evidence = record["evidence"]
    return "\n".join(
        [
            'schema_version: "1"',
            'kind: "revocation"',
            f'approval_id: "{record["approval_id"]}"',
            f"pull_request: {record['pull_request']}",
            f'github_login: "{record["github_login"]}"',
            "evidence:",
            f'  comment_id: "{evidence["comment_id"]}"',
            f'  comment_url: "{evidence["comment_url"]}"',
            f'  workflow_run_id: "{evidence["workflow_run_id"]}"',
            f'  comment_body: "{evidence["comment_body"]}"',
            "",
        ]
    )


def dump_governance(record: dict) -> str:
    reviewer = record["reviewer"]
    evidence = record["evidence"]
    lines = [
        'schema_version: "1"',
        'kind: "governance"',
        f'approval_id: "{record["approval_id"]}"',
        f"pull_request: {record['pull_request']}",
        "reviewer:",
        f'  github_login: "{reviewer["github_login"]}"',
        f'  name: "{reviewer["name"]}"',
        f'  role: "{reviewer["role"]}"',
        f'approved_at: "{record["approved_at"]}"',
        f'approved_commit: "{record["approved_commit"]}"',
        "files:",
    ]
    for item in record["files"]:
        lines.append(f'  - path: "{item["path"]}"')
        lines.append(f'    sha256: "{item["sha256"]}"')
    lines.extend(
        [
            "evidence:",
            f'  comment_id: "{evidence["comment_id"]}"',
            f'  comment_url: "{evidence["comment_url"]}"',
            f'  workflow_run_id: "{evidence["workflow_run_id"]}"',
            f'  comment_body: "{evidence["comment_body"]}"',
            "",
        ]
    )
    return "\n".join(lines)


def workflow_path(path: str) -> str:
    # GitHub may return e.g. .github/workflows/test-approval.yml@main.
    return path.partition("@")[0]


def accepted_receipt(policy: Policy, run: WorkflowRun) -> dict | None:
    """Return the receipt stored by a successful trusted run, or nothing."""
    if (
        run.conclusion != "success"
        or workflow_path(run.path) != policy.trusted_workflow
        or run.event != "issue_comment"
        or not run.receipt
    ):
        return None
    try:
        data = parse_yaml(run.receipt)
        kind = str(data.get("kind") or "")
        if kind == "revocation":
            parsed = normalize_revocation(data)
            actor = parsed["github_login"]
        elif kind == "governance":
            parsed = normalize_governance(data)
            actor = parsed["reviewer"]["github_login"]
        elif kind == "approval":
            parsed = normalize_record(data)
            actor = parsed["approver"]["github_login"]
        else:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    evidence = parsed["evidence"]
    if evidence["workflow_run_id"] != run.run_id or run.actor != actor:
        return None
    if run.display_title != f"gate-comment-{evidence['comment_id']}":
        return None
    if evidence["comment_body"].strip() != evidence["comment_body"]:
        return None
    return parsed


def discover_plans(repo: Path, commits: list[str], policy: Policy) -> list[str]:
    found = []
    for sha in commits:
        for path in commit_changes(repo, sha):
            if classify(path, policy) == "plan" and path not in found:
                found.append(path)
    return found


def implementation_commits(repo: Path, commits: list[str], policy: Policy) -> list[str]:
    found = []
    for sha in commits:
        kinds = {classify(path, policy) for path in commit_changes(repo, sha)}
        if "implementation" in kinds:
            found.append(sha)
    return found


def order_problem(repo: Path, impl: list[str], approved: str) -> str | None:
    if any(sha != approved and is_ancestor(repo, sha, approved) for sha in impl):
        return "implementation was already present at approval"
    if approved in impl:
        return "approval and implementation are the same commit"
    if impl and not (is_ancestor(repo, approved, impl[0]) and approved != impl[0]):
        return "approved commit is not a strict ancestor of the first implementation commit"
    return None


def build_record(
    policy: Policy,
    plan_path: str,
    plan: dict,
    plan_hash: str,
    tests: list[dict[str, str]],
    comment: Comment,
    run: WorkflowRun,
) -> dict:
    approved = command_sha(policy, comment.body)
    if approved is None:
        raise ValueError("approval comment is not the exact command")
    approver = policy.approvers[comment.user]
    return {
        "schema_version": "1",
        "kind": "approval",
        "approval_id": f"ta-{approved[:12]}-{comment.comment_id}",
        "feature_id": plan["feature_id"],
        "pull_request": comment.pull_request,
        "approver": approver,
        "approved_at": comment.created_at,
        "approved_commit": approved,
        "plan": {"path": plan_path, "sha256": plan_hash},
        "scope": {
            "requirements": list(plan["requirements"]),
            "implementation_paths": list(plan["implementation_paths"]),
            "test_files": tests,
        },
        "evidence": {
            "comment_id": comment.comment_id,
            "comment_url": comment.url,
            "workflow_run_id": run.run_id,
            "comment_body": f"{policy.approve_command} {approved}",
        },
    }


def content_fingerprint(repo: Path, sha: str, path: str) -> str:
    blob = file_bytes(repo, sha, path)
    if blob is None:
        return "deleted"
    return digest(blob)


def assess(
    repo: Path,
    policy: Policy,
    base: str,
    head: str,
    pull_request: int,
    author: str,
    evidence: Evidence,
) -> Result:
    def failed(*lines: str) -> Result:
        return Result("failed", head, lines)

    merge_base, commits = pull_commits(repo, base, head)
    touched: list[str] = []
    for sha in commits:
        for path in commit_changes(repo, sha):
            if path not in touched:
                touched.append(path)
    kinds = {path: classify(path, policy) for path in touched}
    if any(kind == "governance" for kind in kinds.values()):
        return assess_governance(repo, policy, head, pull_request, author, evidence, commits, touched, kinds)
    if any(kind == "unknown" for kind in kinds.values()):
        unknown = [path for path, kind in kinds.items() if kind == "unknown"]
        return failed("unclassified path is not treated as documentation-only: " + ", ".join(unknown))
    applicable = [path for path, kind in kinds.items() if kind in {"implementation", "test", "plan", "approval"}]
    if not applicable:
        return Result("not applicable", head, ("Ordinary documentation, images, or archived results do not need test approval.",))

    if not policy.roster_confirmed or not policy.approvers:
        return failed("the protected baseline has no confirmed approver roster")

    receipts = []
    revoked = set()
    other_pr = False
    for run in evidence.runs:
        parsed = accepted_receipt(policy, run)
        if parsed is None:
            continue
        if parsed["pull_request"] != pull_request:
            other_pr = True
            continue
        if parsed["kind"] == "revocation":
            revoked.add(parsed["approval_id"])
        elif parsed["kind"] == "approval":
            receipts.append((parsed, run))

    if not receipts:
        saw_self = False
        saw_unauthorized = False
        saw_untrusted = False
        for comment in evidence.comments:
            if comment.pull_request != pull_request:
                if command_sha(policy, comment.body):
                    other_pr = True
                continue
            approved = command_sha(policy, comment.body)
            if approved is None:
                if comment.body.strip().startswith(policy.approve_command):
                    saw_untrusted = True
                continue
            if comment.user == author:
                saw_self = True
            elif comment.user not in policy.approvers:
                saw_unauthorized = True
            else:
                saw_untrusted = True
        if saw_self:
            return failed("self-approval is not accepted")
        if saw_unauthorized:
            return failed("approver is not on the protected roster")
        if other_pr:
            return failed("approval belongs to another pull request")
        if saw_untrusted:
            return failed("the approval command was not accepted by the trusted workflow")
        return failed("no test approval")

    plans = discover_plans(repo, commits, policy)
    errors = []
    for receipt, run in receipts:
        comment = next((item for item in evidence.comments if item.comment_id == receipt["evidence"]["comment_id"]), None)
        if comment is None or comment.pull_request != pull_request:
            errors.append("approval comment was deleted")
            continue
        if comment.user == author:
            errors.append("self-approval is not accepted")
            continue
        if comment.user not in policy.approvers:
            errors.append("approver is not on the protected roster")
            continue
        if comment.body.strip() != receipt["evidence"]["comment_body"]:
            errors.append("approval comment was edited after the trusted workflow accepted it")
            continue
        if receipt["approval_id"] in revoked:
            return failed("approval was revoked")
        problem = validate_candidate(
            repo, policy, merge_base, commits, plans, comment, run, receipt, pull_request, head
        )
        if problem is None:
            return Result("passed", head, (f"Approved {receipt['approved_commit']} in comment {comment.comment_id}.",))
        errors.append(problem)
    return failed(*errors)


def assess_governance(
    repo: Path,
    policy: Policy,
    head: str,
    pull_request: int,
    author: str,
    evidence: Evidence,
    commits: list[str],
    touched: list[str],
    kinds: dict[str, str],
) -> Result:
    def failed(*lines: str) -> Result:
        return Result("failed", head, lines)

    blocked = [path for path, kind in kinds.items() if kind in {"implementation", "test", "plan", "approval", "unknown"}]
    if blocked:
        return failed(
            "governance review does not cover: "
            + ", ".join(blocked)
            + ". Split those changes out of the gate change."
        )
    if not policy.governance_roster_confirmed or not policy.governance_reviewers:
        return failed("the protected baseline has no confirmed governance reviewers")
    receipts = []
    for run in evidence.runs:
        parsed = accepted_receipt(policy, run)
        if parsed and parsed["kind"] == "governance" and parsed["pull_request"] == pull_request:
            receipts.append((parsed, run))
    if not receipts:
        return failed("gate files changed and need /approve-governance from a baseline governance reviewer")
    errors = []
    for receipt, _run in receipts:
        comment = next((item for item in evidence.comments if item.comment_id == receipt["evidence"]["comment_id"]), None)
        if comment is None or comment.pull_request != pull_request:
            errors.append("governance approval comment was deleted")
            continue
        if comment.body.strip() != receipt["evidence"]["comment_body"]:
            errors.append("governance approval comment was edited after the trusted workflow accepted it")
            continue
        if comment.user == author:
            errors.append("self-approval is not accepted")
            continue
        if comment.user not in policy.governance_reviewers:
            errors.append("approver is not on the protected governance roster")
            continue
        problem = validate_governance(repo, policy, commits, touched, kinds, comment, receipt, head)
        if problem is None:
            return Result("passed", head, (f"Governance review {receipt['approval_id']} matches {receipt['approved_commit']}.",))
        errors.append(problem)
    return failed(*errors)


def validate_governance(
    repo: Path,
    policy: Policy,
    commits: list[str],
    touched: list[str],
    kinds: dict[str, str],
    comment: Comment,
    receipt: dict,
    head: str,
) -> str | None:
    approved = receipt["approved_commit"]
    if comment.user != receipt["reviewer"]["github_login"]:
        return "governance receipt does not match the approving comment"
    if not is_ancestor(repo, approved, head):
        return "approved commit is not an ancestor of the latest commit"
    if approved not in commits and approved != head:
        return "approved commit is not in this pull request"
    governed = [path for path in touched if kinds[path] == "governance"]
    fingerprinted = {item["path"]: item["sha256"] for item in receipt["files"]}
    if set(fingerprinted) != set(governed):
        return "governance receipt does not cover the gate files changed in this pull request"
    for path, recorded in fingerprinted.items():
        if content_fingerprint(repo, approved, path) != recorded or content_fingerprint(repo, head, path) != recorded:
            return f"governance file changed after approval: {path}"
    rebuilt = governance_record(policy, comment, receipt["evidence"]["workflow_run_id"], approved, governed, repo)
    if rebuilt != receipt:
        return "governance receipt does not match the approved commit"
    return None


def governance_record(
    policy: Policy,
    comment: Comment,
    workflow_run_id: str,
    approved: str,
    paths: list[str],
    repo: Path,
) -> dict:
    reviewer = policy.governance_reviewers[comment.user]
    files = [{"path": path, "sha256": content_fingerprint(repo, approved, path)} for path in sorted(paths)]
    return {
        "schema_version": "1",
        "kind": "governance",
        "approval_id": f"tg-{approved[:12]}-{comment.comment_id}",
        "pull_request": comment.pull_request,
        "reviewer": reviewer,
        "approved_at": comment.created_at,
        "approved_commit": approved,
        "files": files,
        "evidence": {
            "comment_id": comment.comment_id,
            "comment_url": comment.url,
            "workflow_run_id": workflow_run_id,
            "comment_body": f"{policy.governance_command} {approved}",
        },
    }


def validate_candidate(
    repo: Path,
    policy: Policy,
    merge_base: str,
    commits: list[str],
    plans: list[str],
    comment: Comment,
    run: WorkflowRun,
    receipt: dict | None,
    pull_request: int,
    head: str,
    sink: list[dict] | None = None,
) -> str | None:
    approved = receipt["approved_commit"] if receipt is not None else command_sha(policy, comment.body)
    if approved is None:
        return "the approval command must be /approve-tests followed by the full 40-character commit SHA"
    if receipt is not None and comment.user != receipt["approver"]["github_login"]:
        return "approval receipt does not match the approving comment"
    if comment.user == "" or comment.pull_request != pull_request:
        return "approval belongs to another pull request"
    if not is_ancestor(repo, approved, head) and approved != head:
        return "approved commit is not an ancestor of the latest commit"
    if approved not in commits and approved != head:
        return "approved commit is not in this pull request"
    if len(plans) != 1:
        return "this pull request must contain exactly one test plan"
    plan_path = plans[0]
    plan_blob = file_bytes(repo, approved, plan_path)
    if plan_blob is None:
        return "approved commit does not contain the test plan"
    try:
        plan = front_matter(plan_blob.decode())
    except ValueError as exc:
        return str(exc)
    plan_error = validate_plan(plan)
    if plan_error:
        return plan_error
    if not plan_path.endswith(f"/{plan['feature_id']}.md"):
        return "plan path does not match its feature id"
    for path in plan["test_files"]:
        if classify(path, policy) != "test":
            return f"listed test file is outside the verification paths: {path}"
    for path in plan["implementation_paths"]:
        if classify(path, policy) != "implementation":
            return f"listed implementation path is outside the implementation rules: {path}"
    impl = implementation_commits(repo, commits, policy)
    problem = order_problem(repo, impl, approved)
    if problem:
        return problem
    outside = []
    for sha in impl:
        for path in commit_changes(repo, sha):
            if classify(path, policy) == "implementation" and not covers(path, plan["implementation_paths"]):
                outside.append(path)
    if outside:
        return "implementation is outside the approved scope: " + ", ".join(sorted(set(outside)))
    test_paths = []
    for sha in commits:
        for path in commit_changes(repo, sha):
            if classify(path, policy) == "test" and path not in test_paths:
                test_paths.append(path)
    unlisted = [path for path in test_paths if path not in plan["test_files"]]
    if unlisted:
        return "test change is outside the approved scope: " + ", ".join(unlisted)
    head_plan = file_bytes(repo, head, plan_path)
    if head_plan != plan_blob:
        return (
            "plan fingerprint changed after approval. This is not a pre-approval of the new scope. "
            "Split the new work, or record the problem explicitly."
        )
    tests = []
    for path in plan["test_files"]:
        blob = file_bytes(repo, approved, path)
        if blob is None:
            return f"approved commit does not contain {path}"
        if file_bytes(repo, head, path) != blob:
            return (
                f"test fingerprint changed after approval: {path}. This is not a pre-approval of the new scope. "
                "Split the new work, or record the problem explicitly."
            )
        tests.append({"path": path, "sha256": digest(blob)})
    record = build_record(policy, plan_path, plan, digest(plan_blob), tests, comment, run)
    if sink is not None:
        sink.append(record)
    if receipt is not None and record != receipt:
        return "receipt does not match the approved commit"
    if record["pull_request"] != pull_request:
        return "approval belongs to another pull request"
    return archive_problem(repo, policy, merge_base, head, record, required=bool(impl))


def archive_problem(repo: Path, policy: Policy, merge_base: str, head: str, record: dict, required: bool) -> str | None:
    expected = f"{policy.approval_prefix}{record['approval_id']}.yaml"
    current = set(archives_at(repo, head, policy))
    previous = set(archives_at(repo, merge_base, policy))
    for path in sorted(current | previous):
        if file_bytes(repo, merge_base, path) == file_bytes(repo, head, path):
            continue
        if path != expected:
            return "this pull request changes an approval record that is not its verified approval"
    archived = file_bytes(repo, head, expected)
    if archived is None:
        if required:
            return "the verified approval record is not archived in this pull request"
        return None
    try:
        parsed = normalize_record(parse_yaml(archived.decode()))
    except (ValueError, KeyError, TypeError):
        return "approval record does not match the trusted GitHub approval"
    if parsed != record:
        return "approval record does not match the trusted GitHub approval"
    return None


def archives_at(repo: Path, sha: str, policy: Policy) -> list[str]:
    listing = git(repo, ["ls-tree", "-r", "--name-only", sha, policy.approval_prefix])
    if listing.returncode != 0:
        return []
    paths = []
    for line in listing.stdout.decode().splitlines():
        if classify(line, policy) == "approval":
            paths.append(line)
    return paths


def prepare_approval(
    repo: Path,
    policy: Policy,
    base: str,
    head: str,
    pull_request: int,
    author: str,
    comment: Comment,
    workflow_run_id: str,
) -> tuple[dict | None, str | None]:
    """Validate a command and build its receipt. This does not publish a check."""
    approved = command_sha(policy, comment.body)
    if approved is None:
        return None, "the approval command must be /approve-tests followed by the full 40-character commit SHA"
    if comment.pull_request != pull_request:
        return None, "approval belongs to another pull request"
    if comment.user == author:
        return None, "self-approval is not accepted"
    if comment.user not in policy.approvers or not policy.roster_confirmed:
        return None, "approver is not on the protected roster"
    if approved != head:
        return None, "the command does not point at the current pull request head"
    run = WorkflowRun(
        workflow_run_id,
        policy.trusted_workflow,
        "issue_comment",
        "success",
        f"gate-comment-{comment.comment_id}",
        comment.user,
    )
    merge_base, commits = pull_commits(repo, base, head)
    plans = discover_plans(repo, commits, policy)
    sink: list[dict] = []
    problem = validate_candidate(
        repo, policy, merge_base, commits, plans, comment, run, None, pull_request, head, sink
    )
    if problem:
        return None, problem
    if not sink:
        return None, "approval was not accepted"
    return sink[0], None


def prepare_governance(
    repo: Path,
    policy: Policy,
    base: str,
    head: str,
    pull_request: int,
    author: str,
    comment: Comment,
    workflow_run_id: str,
) -> tuple[dict | None, str | None]:
    approved = governance_sha(policy, comment.body)
    if approved is None:
        return None, "the governance command must be /approve-governance followed by the full 40-character commit SHA"
    if comment.pull_request != pull_request:
        return None, "approval belongs to another pull request"
    if comment.user == author:
        return None, "self-approval is not accepted"
    if comment.user not in policy.governance_reviewers or not policy.governance_roster_confirmed:
        return None, "approver is not on the protected governance roster"
    if approved != head:
        return None, "the command does not point at the current pull request head"
    _merge_base, commits = pull_commits(repo, base, head)
    touched: list[str] = []
    for sha in commits:
        for path in commit_changes(repo, sha):
            if path not in touched:
                touched.append(path)
    kinds = {path: classify(path, policy) for path in touched}
    blocked = [path for path, kind in kinds.items() if kind in {"implementation", "test", "plan", "approval", "unknown"}]
    if blocked:
        return None, "governance review does not cover: " + ", ".join(blocked) + ". Split those changes out of the gate change."
    governed = [path for path in touched if kinds[path] == "governance"]
    if not governed:
        return None, "the command does not approve a gate change"
    record = governance_record(policy, comment, workflow_run_id, approved, governed, repo)
    problem = validate_governance(repo, policy, commits, touched, kinds, comment, record, head)
    if problem:
        return None, problem
    return record, None


def github_json(url: str, token: str, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "test-approval-gate",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def next_page(link: str | None) -> str | None:
    if not link:
        return None
    for part in link.split(","):
        section, _, relation = part.partition(";")
        if 'rel="next"' in relation:
            return section.strip().removeprefix("<").removesuffix(">")
    return None


def github_pages(url: str, token: str, key: str | None = None) -> list:
    items = []
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "test-approval-gate",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
            url = next_page(response.headers.get("Link"))
        items.extend(payload if key is None else payload.get(key, []))
    return items


def github_bytes(url: str, token: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "test-approval-gate",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def download_receipt(repository: str, token: str, run_id: str) -> str:
    artifacts = github_pages(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        token,
        "artifacts",
    )
    chosen = None
    for artifact in artifacts:
        name = str(artifact.get("name") or "")
        if name.startswith("test-approval-") and name != "test-approval-context" and not artifact.get("expired"):
            chosen = artifact
            break
    if chosen is None:
        return ""
    blob = github_bytes(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{chosen['id']}/zip",
        token,
    )
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [name for name in archive.namelist() if name == "approval.yaml"]
        if not names:
            return ""
        return archive.read(names[0]).decode()


def load_github_evidence(repository: str, pull_request: int, token: str) -> Evidence:
    comments = []
    comment_url = f"https://api.github.com/repos/{repository}/issues/{pull_request}/comments?per_page=100"
    for item in github_pages(comment_url, token):
        comments.append(
            Comment(
                str(item["id"]),
                item["html_url"],
                item["user"]["login"],
                item["body"],
                item["created_at"],
                pull_request,
            )
        )
    runs = []
    run_url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/"
        "test-approval.yml/runs?event=issue_comment&per_page=100"
    )
    for item in github_pages(run_url, token, "workflow_runs"):
        actor = (item.get("actor") or {}).get("login", "")
        receipt = ""
        if (item.get("conclusion") or "") == "success":
            receipt = download_receipt(repository, token, str(item["id"]))
        runs.append(
            WorkflowRun(
                str(item["id"]),
                item.get("path", ""),
                item.get("event", ""),
                item.get("conclusion") or "",
                item.get("display_title") or "",
                actor,
                receipt,
            )
        )
    return Evidence(tuple(comments), tuple(runs))


def publish_check(
    repository: str,
    token: str,
    head: str,
    result: Result,
    check_run_id: str = "",
    conclusion: str = "",
) -> str:
    if not conclusion:
        conclusion = "success" if result.exit_code() == 0 else "failure"
    body = {
        "name": "test approval",
        "head_sha": head,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": result.status, "summary": result.text()},
    }
    if check_run_id:
        url = f"https://api.github.com/repos/{repository}/check-runs/{check_run_id}"
        existing = github_json(url, token)
        if existing.get("head_sha") != head or existing.get("name") != "test approval":
            raise RuntimeError("the check being updated is not bound to this PR revision")
        # The update endpoint cannot move a check to another commit.
        body.pop("head_sha")
        github_json(url, token, "PATCH", body)
        return check_run_id
    created = github_json(f"https://api.github.com/repos/{repository}/check-runs", token, "POST", body)
    return str(created["id"])


def open_check(repository: str, token: str, head: str) -> str:
    created = github_json(
        f"https://api.github.com/repos/{repository}/check-runs",
        token,
        "POST",
        {
            "name": "test approval",
            "head_sha": head,
            "status": "in_progress",
            "external_id": "test-approval:" + os.environ.get("GITHUB_RUN_ID", ""),
            "output": {
                "title": "in progress",
                "summary": "Test approval has not finished. A green result is published only after the receipt is stored.",
            },
        },
    )
    return str(created["id"])


def write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def post_comment(repository: str, token: str, pull_request: int, body: str) -> None:
    github_json(
        f"https://api.github.com/repos/{repository}/issues/{pull_request}/comments",
        token,
        "POST",
        {"body": body},
    )


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def commit_exists(repo: Path, sha: str) -> bool:
    return git(repo, ["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0


def fetch_commit(repo: Path, sha: str) -> None:
    if commit_exists(repo, sha):
        return
    result = git(repo, ["fetch", "--no-tags", "origin", sha])
    if result.returncode != 0 or not commit_exists(repo, sha):
        detail = result.stderr.decode() or result.stdout.decode()
        raise RuntimeError(detail or f"could not fetch {sha}")


def fetch_pull_head(repo: Path, pull_request: int, expected: str) -> None:
    result = git(repo, ["fetch", "--no-tags", "origin", f"pull/{pull_request}/head"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode() or "could not fetch the pull request")
    fetched = git_text(repo, ["rev-parse", "FETCH_HEAD"]).strip()
    if fetched != expected:
        raise RuntimeError("fetched pull request head does not match the event SHA")


def pull_from_api(repository: str, token: str, number: int) -> tuple[str, str, str]:
    pull = github_json(f"https://api.github.com/repos/{repository}/pulls/{number}", token)
    return pull["base"]["sha"], pull["head"]["sha"], pull["user"]["login"]


def resolve_check_target(repo: Path) -> tuple[str, str, int, str]:
    event = event_payload()
    pull = event.get("pull_request")
    if pull:
        base = pull["base"]["sha"]
        head = pull["head"]["sha"]
        number = int(pull["number"])
        author = pull["user"]["login"]
        fetch_commit(repo, base)
        fetch_pull_head(repo, number, head)
        return base, head, number, author
    issue = event.get("issue") or {}
    if issue.get("pull_request"):
        number = int(issue["number"])
        base, head, author = pull_from_api(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"], number)
        fetch_commit(repo, base)
        fetch_pull_head(repo, number, head)
        return base, head, number, author
    return os.environ["BASE_SHA"], os.environ["HEAD_SHA"], int(os.environ["PR_NUMBER"]), os.environ["PR_AUTHOR"]


def resolve_comment_target(repo: Path, repository: str, token: str) -> tuple[str, str, int, str, Comment]:
    event = event_payload()
    raw = event.get("comment")
    issue = event.get("issue") or {}
    if raw and issue.get("pull_request"):
        number = int(issue["number"])
        author = issue["user"]["login"]
        comment = Comment(
            str(raw["id"]),
            raw["html_url"],
            raw["user"]["login"],
            raw.get("body") or "",
            raw["created_at"],
            number,
        )
        base, head, author = pull_from_api(repository, token, number)
        fetch_commit(repo, base)
        fetch_pull_head(repo, number, head)
        return base, head, number, author, comment
    number = int(os.environ["PR_NUMBER"])
    return (
        os.environ["BASE_SHA"],
        os.environ["HEAD_SHA"],
        number,
        os.environ["PR_AUTHOR"],
        Comment(
            os.environ["COMMENT_ID"],
            os.environ["COMMENT_URL"],
            os.environ["COMMENT_USER"],
            os.environ["COMMENT_BODY"],
            os.environ["COMMENT_AT"],
            number,
        ),
    )


def run_check_from_env(publish: bool) -> int:
    repo = Path.cwd()
    policy = load_policy((repo / "docs/code-governance/test-approval-policy.yaml").read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    base, head, pull_request, author = resolve_check_target(repo)
    if token and repository:
        evidence = load_github_evidence(repository, pull_request, token)
    else:
        evidence = Evidence()
    result = assess(repo, policy, base, head, pull_request, author, evidence)
    print(result.text())
    if publish:
        if not token or not repository:
            print("cannot attach test approval to the head SHA without GitHub credentials")
            return 1
        publish_check(repository, token, head, result, os.environ.get("CHECK_RUN_ID", ""))
    return result.exit_code()


def render_receipt(record: dict) -> str:
    if record["kind"] == "revocation":
        return dump_revocation(record)
    if record["kind"] == "governance":
        return dump_governance(record)
    return dump_record(record)


def revocation_record(comment: Comment, workflow_run_id: str, approval_id: str) -> dict:
    return {
        "schema_version": "1",
        "kind": "revocation",
        "approval_id": approval_id,
        "pull_request": comment.pull_request,
        "github_login": comment.user,
        "evidence": {
            "comment_id": comment.comment_id,
            "comment_url": comment.url,
            "workflow_run_id": workflow_run_id,
            "comment_body": comment.body.strip(),
        },
    }


def run_prepare_from_env(output: str | None, post: bool) -> int:
    repo = Path.cwd()
    policy = load_policy((repo / "docs/code-governance/test-approval-policy.yaml").read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if event_payload().get("comment") and not (token and repository):
        print("cannot read the pull request without GitHub credentials")
        return 1
    base, head, pull_request, author, comment = resolve_comment_target(repo, repository, token)
    target = revoke_target(policy, comment.body)
    if target is not None:
        allowed = (comment.user in policy.approvers or comment.user == author) and policy.roster_confirmed
        if not allowed:
            message = "revocation was not accepted"
            print(message)
            if post and token and repository:
                post_comment(repository, token, pull_request, f"test-approval-rejected\n\n{message}")
            return 1
        record = revocation_record(comment, os.environ["GITHUB_RUN_ID"], target)
        rendered = render_receipt(record)
        if output:
            Path(output).write_text(rendered, encoding="utf-8")
        if post and token and repository:
            post_comment(
                repository,
                token,
                pull_request,
                f"test-approval-revoked approval_id={target}\n\nThe approval is withdrawn. A comment alone is not the record; this workflow run is.",
            )
        print(rendered)
        return 0
    if governance_sha(policy, comment.body) is not None:
        record, error = prepare_governance(
            repo, policy, base, head, pull_request, author, comment, os.environ["GITHUB_RUN_ID"]
        )
        accepted = "governance review"
    else:
        record, error = prepare_approval(
            repo, policy, base, head, pull_request, author, comment, os.environ["GITHUB_RUN_ID"]
        )
        accepted = "test approval"
    if error or record is None:
        print(error or "approval was not accepted")
        if post and token and repository:
            post_comment(repository, token, pull_request, f"test-approval-rejected\n\n{error}")
        return 1
    rendered = render_receipt(record)
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
    print(rendered)
    if post and token and repository:
        post_comment(
            repository,
            token,
            pull_request,
            "\n".join(
                [
                    f"test-approval-receipt approval_id={record['approval_id']}",
                    "",
                    f"The receipt for this {accepted} was stored. Final acceptance awaits successful workflow completion and revalidation.",
                    "Editing or deleting the command invalidates it. A copied YAML file is not an approval.",
                    "",
                    "```yaml",
                    rendered.rstrip(),
                    "```",
                ]
            ),
        )
    return 0


def resolved_head(repo: Path) -> str:
    event = event_payload()
    if event.get("pull_request") or (event.get("issue") or {}).get("pull_request"):
        _base, head, _number, _author = resolve_check_target(repo)
        return head
    if os.environ.get("HEAD_SHA"):
        return os.environ["HEAD_SHA"]
    return resolve_check_target(repo)[1]


def run_open_check() -> int:
    _base, head, number, _author = resolve_check_target(Path.cwd())
    repository = os.environ["GITHUB_REPOSITORY"]
    check_id = open_check(repository, os.environ["GITHUB_TOKEN"], head)
    write_github_output("check_run_id", check_id)
    context_path = os.environ.get("CHECK_CONTEXT_PATH", "")
    if context_path:
        Path(context_path).write_text(json.dumps({
            "repository": repository,
            "pull_request": number,
            "head_sha": head,
            "check_run_id": check_id,
            "workflow_run_id": os.environ["GITHUB_RUN_ID"],
        }), encoding="utf-8")
    print(check_id)
    return 0


def run_finalize(message: str) -> int:
    """Validate the local artifact but never mark a running producer green."""
    receipt_path = os.environ.get("RECEIPT_PATH", "")
    if not receipt_path or not Path(receipt_path).is_file():
        raise RuntimeError("the producer has no receipt to finalize")
    receipt = Path(receipt_path).read_text(encoding="utf-8")
    policy = load_policy((Path.cwd() / "docs/code-governance/test-approval-policy.yaml").read_text())
    raw = event_payload().get("comment") or {}
    run = WorkflowRun(
        os.environ["GITHUB_RUN_ID"], policy.trusted_workflow, "issue_comment",
        "success", f"gate-comment-{raw.get('id', '')}",
        (raw.get("user") or {}).get("login", ""), receipt,
    )
    if accepted_receipt(policy, run) is None:
        raise RuntimeError("the producer receipt is invalid")
    print(message or "Receipt ready; test approval remains in progress until this workflow completes.")
    return 0


def completed_context(repository: str, token: str, run_id: str) -> dict:
    artifacts = github_pages(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        token, "artifacts",
    )
    matches = [item for item in artifacts if item.get("name") == "test-approval-context" and not item.get("expired")]
    if len(matches) != 1:
        raise RuntimeError("the producer has no unique retained check context; no success can be published")
    blob = github_bytes(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{matches[0]['id']}/zip", token,
    )
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return json.loads(archive.read("test-approval-context.json"))


def finish_completed_run(repo: Path, repository: str, token: str, raw_run: dict) -> Result | None:
    """Recheck only after the trusted receipt producer is actually complete."""
    policy = load_policy((repo / "docs/code-governance/test-approval-policy.yaml").read_text())
    if raw_run.get("event") != "issue_comment":
        return None
    if workflow_path(str(raw_run.get("path") or "")) != policy.trusted_workflow or raw_run.get("status") != "completed":
        raise RuntimeError("completion event is not from the completed trusted workflow")
    if (raw_run.get("repository") or {}).get("full_name") != repository:
        raise RuntimeError("completion event belongs to another repository")
    run_id = str(raw_run["id"])
    jobs = github_pages(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100", token, "jobs",
    )
    producers = [job for job in jobs if job.get("name") == "record-approval"]
    # Ordinary comment rechecks already publish their own result. They do not
    # create an approval receipt and must not be mistaken for producers.
    if not producers or all(job.get("conclusion") == "skipped" for job in producers):
        return None
    context = completed_context(repository, token, run_id)
    if context.get("repository") != repository or str(context.get("workflow_run_id")) != run_id:
        raise RuntimeError("check context belongs to a different producer")
    head = context.get("head_sha", "")
    number = context.get("pull_request")
    check_id = str(context.get("check_run_id", ""))
    if not FULL_SHA.fullmatch(head) or not isinstance(number, int) or number < 1 or not check_id.isdigit():
        raise RuntimeError("invalid producer check context")
    check = github_json(f"https://api.github.com/repos/{repository}/check-runs/{check_id}", token)
    if (check.get("head_sha") != head or check.get("name") != "test approval"
            or check.get("external_id") != f"test-approval:{run_id}"):
        raise RuntimeError("producer context does not match the opened check")

    def failure(reason: str) -> Result:
        result = Result("failed", head, (reason,))
        publish_check(repository, token, head, result, check_id, "failure")
        return result

    if raw_run.get("conclusion") != "success" or any(job.get("conclusion") != "success" for job in producers):
        return failure("The receipt workflow failed or was cancelled; approval was not accepted.")
    receipt = download_receipt(repository, token, run_id)
    run = WorkflowRun(
        run_id, raw_run["path"], raw_run["event"], raw_run["conclusion"],
        raw_run.get("display_title", ""), (raw_run.get("actor") or {}).get("login", ""), receipt,
    )
    parsed = accepted_receipt(policy, run)
    if parsed is None or parsed["pull_request"] != number:
        return failure("The completed producer has no valid matching receipt.")
    try:
        base, latest, author = pull_from_api(repository, token, number)
        fetch_commit(repo, base)
        fetch_pull_head(repo, number, latest)
        evidence = load_github_evidence(repository, number, token)
        # API list responses can lag behind the completion event. Include the
        # independently downloaded receipt from this completed producer.
        evidence = Evidence(evidence.comments, tuple(item for item in evidence.runs if item.run_id != run_id) + (run,))
        result = assess(repo, policy, base, latest, number, author, evidence)
        if latest != head:
            failure("The PR changed while approval was processing; the current head was checked separately.")
            publish_check(repository, token, latest, result)
        else:
            publish_check(repository, token, head, result, check_id)
        return result
    except (OSError, RuntimeError, KeyError, ValueError):
        failure("The completed approval could not be revalidated; no success was published.")
        raise


def run_complete_from_env() -> int:
    raw = event_payload().get("workflow_run") or {}
    result = finish_completed_run(
        Path.cwd(), os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"], raw,
    )
    print(result.text() if result is not None else "No receipt producer to finalize.")
    return 0


def run_publish_failure(message: str) -> int:
    try:
        head = resolved_head(Path.cwd())
    except (KeyError, RuntimeError, OSError):
        event = event_payload()
        pull = event.get("pull_request") or {}
        head = (pull.get("head") or {}).get("sha") or os.environ.get("HEAD_SHA", "")
    result = Result("failed", head, (message,))
    publish_check(
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_TOKEN"],
        head,
        result,
        os.environ.get("CHECK_RUN_ID", ""),
        "failure",
    )
    print(result.text())
    return 1


def expect(condition: bool, label: str, failures: list[str]) -> None:
    print(("pass: " if condition else "fail: ") + label)
    if not condition:
        failures.append(label)


def plan_text(feature: str = "sample-feature", implementation: list[str] | None = None) -> str:
    paths = ["tradingagents/feature.py"] if implementation is None else implementation
    path_lines = "\n".join(f'  - "{item}"' for item in paths) or " []"
    implementation_block = "implementation_paths:\n" + path_lines if paths else "implementation_paths: []"
    return "\n".join(
        [
            "---",
            f'feature_id: "{feature}"',
            "requirements:",
            '  - "REQ-SAMPLE-1"',
            implementation_block,
            "test_files:",
            '  - "tests/test_sample.py"',
            "cases:",
            '  - id: "normal-case"',
            '    kind: "normal"',
            '    expected: "The normal input produces the stated result."',
            '  - id: "boundary-case"',
            '    kind: "boundary"',
            '    expected: "The boundary input stays explicit."',
            '  - id: "error-case"',
            '    kind: "error"',
            '    expected: "A broken input finishes incomplete."',
            '  - id: "security-case"',
            '    kind: "security"',
            '    expected: "Injected text does not change the decision."',
            'pass_condition: "All four expectations hold and the listed test passes."',
            "---",
            "",
            "Reviewer notes.",
            "",
        ]
    )


def self_test() -> int:
    failures: list[str] = []
    real_text = (repo_root_from_script() / "docs/code-governance/test-approval-policy.yaml").read_text(encoding="utf-8")
    real = load_policy(real_text)
    expect(real.approve_command == "/approve-tests" and real.governance_command == "/approve-governance", "baseline commands are explicit", failures)
    # This parsing fixture must not depend on who is on the live roster.
    fixture = "\n".join([
        "roster_confirmed: true",
        "approvers:",
        '  - github_login: "fixture-reviewer"',
        '    name: "Fixture Reviewer"',
        '    role: "C"',
        'plan_prefix: "docs/verification/plans/"',
        'approval_prefix: "docs/verification/approvals/"',
        'trusted_workflow: ".github/workflows/test-approval.yml"',
        'approve_command: "/approve-tests"',
        'revoke_command: "/revoke-tests"',
        'governance_command: "/approve-governance"',
    ])
    filled_policy = load_policy(fixture)
    expect(
        filled_policy.roster_confirmed
        and filled_policy.approvers.get("fixture-reviewer", {}).get("role") == "C",
        "a confirmed roster fixture parses independently of the live roster",
        failures,
    )
    expect(
        next_page('<https://example.test/2>; rel="next", <https://example.test/1>; rel="prev"') == "https://example.test/2",
        "a later evidence page is followed",
        failures,
    )
    expect(validate_plan(front_matter(plan_text())) is None, "a complete plan is accepted", failures)
    incomplete = plan_text().replace('    kind: "security"\n', '    kind: "normal"\n')
    expect(validate_plan(front_matter(incomplete)) is not None, "a plan without a security case is rejected", failures)

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        baseline = root / "baseline-policy.yaml"
        baseline.write_text(
            "\n".join(
                [
                    'schema_version: "1"',
                    "roster_confirmed: true",
                    "approvers:",
                    '  - github_login: "reviewer"',
                    '    name: "Reviewer"',
                    '    role: "C"',
                    '  - github_login: "owner"',
                    '    name: "Owner"',
                    '    role: "D"',
                    'implementation_prefixes:',
                    '  - "tradingagents/"',
                    "implementation_files: []",
                    'test_prefixes:',
                    '  - "tests/"',
                    '  - "scripts/"',
                    'governance_prefixes:',
                    '  - ".github/workflows/"',
                    "governance_files:",
                    '  - "scripts/ci/check_test_approval.py"',
                    'not_applicable_prefixes:',
                    '  - "docs/"',
                    "not_applicable_suffixes:",
                    '  - ".png"',
                    'plan_prefix: "docs/verification/plans/"',
                    'approval_prefix: "docs/verification/approvals/"',
                    'trusted_workflow: ".github/workflows/test-approval.yml"',
                    'approve_command: "/approve-tests"',
                    'revoke_command: "/revoke-tests"',
                    "governance_roster_confirmed: true",
                    "governance_reviewers:",
                    '  - github_login: "governor"',
                    '    name: "Governor"',
                    '    role: "E"',
                    '  - github_login: "owner"',
                    '    name: "Owner"',
                    '    role: "D"',
                    'governance_command: "/approve-governance"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        policy = load_policy(baseline.read_text(encoding="utf-8"))
        repo = root / "repo"
        repo.mkdir()
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

        def run(*args: str) -> str:
            result = subprocess.run(args, cwd=repo, env=env, capture_output=True, check=True)
            return result.stdout.decode().strip()

        def put(path: str, content: str | None) -> None:
            target = repo / path
            if content is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        def commit(message: str) -> str:
            run("git", "add", "-A")
            run("git", "commit", "-m", message)
            return run("git", "rev-parse", "HEAD")

        run("git", "init", "-b", "main")
        run("git", "config", "user.email", "gate@example.com")
        run("git", "config", "user.name", "gate")
        put("docs/readme.md", "base\n")
        put(
            "docs/verification/approvals/ta-bbbbbbbbbbbb-9.yaml",
            "\n".join(
                [
                    'schema_version: "1"',
                    'kind: "approval"',
                    'approval_id: "ta-bbbbbbbbbbbb-9"',
                    "pull_request: 9",
                    "",
                ]
            ),
        )
        base = commit("base")

        def approve(sha: str, comment_id: str = "100", user: str = "reviewer", pull: int = 12) -> Evidence:
            comment = Comment(
                comment_id,
                f"https://example.test/comment/{comment_id}",
                user,
                f"/approve-tests {sha}",
                "2026-11-23T01:00:00Z",
                pull,
            )
            run_id = "555" if comment_id == "100" else comment_id
            bare = WorkflowRun(
                run_id,
                policy.trusted_workflow,
                "issue_comment",
                "success",
                f"gate-comment-{comment_id}",
                user,
            )
            _merge_base, commits = pull_commits(repo, base, sha)
            plan_path = discover_plans(repo, commits, policy)[0]
            plan_blob = file_bytes(repo, sha, plan_path) or b""
            plan = front_matter(plan_blob.decode())
            tests = [
                {"path": path, "sha256": digest(file_bytes(repo, sha, path) or b"")}
                for path in plan["test_files"]
            ]
            actor = user if user in policy.approvers else "reviewer"
            source = comment if user in policy.approvers else Comment(
                comment.comment_id, comment.url, actor, comment.body, comment.created_at, comment.pull_request
            )
            record = build_record(policy, plan_path, plan, digest(plan_blob), tests, source, bare)
            if user not in policy.approvers:
                record = dict(record)
                record["approver"] = {"github_login": user, "name": "Stranger", "role": "none"}
            workflow = WorkflowRun(
                run_id,
                policy.trusted_workflow,
                "issue_comment",
                "success",
                f"gate-comment-{comment_id}",
                user,
                dump_record(record),
            )
            return Evidence((comment,), (workflow,))

        def check(head: str, evidence: Evidence, author: str = "owner", pull: int = 12) -> Result:
            return assess(repo, policy, base, head, pull, author, evidence)

        put("docs/guide.md", "ordinary\n")
        put("docs/figure.png", "image\n")
        docs_head = commit("documentation-only")
        docs_result = check(docs_head, Evidence())
        expect(docs_result.status == "not applicable", "ordinary docs and images are not applicable", failures)
        run("git", "reset", "--hard", base)

        put("docs/verification/plans/sample-feature.md", plan_text())
        put("tests/test_sample.py", "def test_sample():\n    assert True\n")
        approved = commit("add plan and tests")
        evidence = approve(approved)
        pre = check(approved, evidence)
        expect(pre.status == "passed", "approved tests with no implementation pass", failures)
        empty_policy = load_policy(
            baseline.read_text(encoding="utf-8").replace("roster_confirmed: true", "roster_confirmed: false", 1)
        )
        empty_result = assess(repo, empty_policy, base, approved, 12, "owner", Evidence())
        expect(
            "no confirmed approver roster" in empty_result.text(),
            "an empty roster fixture rejects applicable changes",
            failures,
        )

        put("tradingagents/feature.py", "VALUE = 1\n")
        implemented = commit("implement feature")
        missing_archive = check(implemented, evidence)
        expect(missing_archive.status == "failed", "implementation without an archived record fails", failures)
        record = build_record(
            policy,
            "docs/verification/plans/sample-feature.md",
            front_matter(plan_text()),
            digest(plan_text().encode()),
            [{"path": "tests/test_sample.py", "sha256": digest(b"def test_sample():\n    assert True\n")}],
            evidence.comments[0],
            evidence.runs[0],
        )
        put(f"docs/verification/approvals/{record['approval_id']}.yaml", dump_record(record))
        archived = commit("archive approval")
        passed = check(archived, evidence)
        expect(passed.status == "passed", "pre-approval followed by in-scope implementation passes", failures)
        expect(
            "ta-bbbbbbbbbbbb-9.yaml" in run("git", "ls-tree", "-r", "--name-only", archived),
            "an older approval record can stay beside the current one",
            failures,
        )
        edited = Comment(
            evidence.comments[0].comment_id,
            evidence.comments[0].url,
            evidence.comments[0].user,
            f"/approve-tests {implemented}",
            evidence.comments[0].created_at,
            12,
        )
        expect(
            "edited" in check(approved, Evidence((edited,), evidence.runs)).text(),
            "an edited approval comment does not keep the old receipt",
            failures,
        )
        expect(
            "deleted" in check(approved, Evidence((), evidence.runs)).text(),
            "a deleted approval comment invalidates its receipt",
            failures,
        )

        run("git", "reset", "--hard", base)
        put("tradingagents/feature.py", "VALUE = 1\n")
        early = commit("implement before approval")
        put("docs/verification/plans/sample-feature.md", plan_text())
        put("tests/test_sample.py", "def test_sample():\n    assert True\n")
        late = commit("add tests after implementation")
        expect(
            "already present" in check(late, approve(late, "201")).text(),
            "approval after implementation already exists fails",
            failures,
        )

        run("git", "reset", "--hard", base)
        put("docs/verification/plans/sample-feature.md", plan_text())
        put("tests/test_sample.py", "def test_sample():\n    assert True\n")
        put("tradingagents/feature.py", "VALUE = 1\n")
        same = commit("tests and implementation together")
        expect(
            "same commit" in check(same, approve(same, "202")).text(),
            "approval and implementation in the same commit fail",
            failures,
        )

        run("git", "reset", "--hard", approved)
        put("tests/test_sample.py", "def test_sample():\n    assert False\n")
        changed_test = commit("change tests after approval")
        expect("test fingerprint" in check(changed_test, evidence).text(), "a changed test fingerprint fails", failures)

        run("git", "reset", "--hard", approved)
        put("tests/test_extra.py", "def test_extra():\n    assert True\n")
        extra = commit("add an unlisted test")
        expect("outside the approved scope" in check(extra, evidence).text(), "an unlisted test change fails", failures)
        put("scripts/check_extra.py", "print('extra')\n")
        scripted = commit("add an unlisted verifier")
        expect(
            "outside the approved scope" in check(scripted, evidence).text(),
            "an unlisted verification script fails",
            failures,
        )

        run("git", "reset", "--hard", approved)
        put("tradingagents/other.py", "OTHER = 1\n")
        outside = commit("implement a different file")
        put(f"docs/verification/approvals/{record['approval_id']}.yaml", dump_record(record))
        outside = commit("archive the original approval")
        expect("outside the approved scope" in check(outside, evidence).text(), "implementation outside the plan fails", failures)

        forged = dict(record)
        forged["evidence"] = dict(record["evidence"])
        forged["evidence"]["workflow_run_id"] = "999"
        run("git", "reset", "--hard", implemented)
        put(f"docs/verification/approvals/{record['approval_id']}.yaml", dump_record(forged))
        forged_head = commit("forged record")
        expect("does not match" in check(forged_head, evidence).text(), "a forged approval record fails", failures)

        foreign = approve(approved, "301", pull=99)
        expect("another pull request" in check(approved, foreign, pull=12).text(), "an approval for another pull request fails", failures)
        expect("self-approval" in check(approved, approve(approved, "302", user="owner")).text(), "self-approval fails", failures)
        expect(
            "not on the protected roster" in check(approved, approve(approved, "303", user="stranger")).text(),
            "an unauthorized approver fails",
            failures,
        )
        expect("no test approval" in check(approved, Evidence()).text(), "missing approval fails", failures)

        revoke_comment = Comment(
            "400",
            "https://example.test/comment/400",
            "reviewer",
            f"/revoke-tests {record['approval_id']}",
            "2026-11-23T02:00:00Z",
            12,
        )
        revoke_run = WorkflowRun(
            "556",
            policy.trusted_workflow,
            "issue_comment",
            "success",
            "gate-comment-400",
            "reviewer",
            dump_revocation(revocation_record(revoke_comment, "556", record["approval_id"])),
        )
        revoked = Evidence(evidence.comments + (revoke_comment,), evidence.runs + (revoke_run,))
        expect("revoked" in check(archived, revoked).text(), "a revoked approval fails", failures)
        withdrawn = Evidence(evidence.comments, evidence.runs + (revoke_run,))
        expect(
            "revoked" in check(archived, withdrawn).text(),
            "a deleted revocation comment still withdraws the approval",
            failures,
        )

        run("git", "reset", "--hard", base)
        put("tradingagents/feature.py", "VALUE = 1\n")
        commit("add implementation")
        put("tradingagents/feature.py", None)
        removed = commit("delete implementation")
        put("docs/verification/plans/sample-feature.md", plan_text())
        put("tests/test_sample.py", "def test_sample():\n    assert True\n")
        after_delete = commit("plan after deletion")
        expect(
            "already present" in check(after_delete, approve(after_delete, "501")).text(),
            "adding and later deleting implementation still counts",
            failures,
        )

        run("git", "reset", "--hard", base)
        put("tradingagents/feature.py", "VALUE = 1\n")
        commit("add file to rename")
        run("git", "mv", "tradingagents/feature.py", "docs/feature.py")
        renamed = commit("move implementation out of the tree")
        put("docs/verification/plans/sample-feature.md", plan_text())
        put("tests/test_sample.py", "def test_sample():\n    assert True\n")
        after_rename = commit("plan after rename")
        expect(
            "already present" in check(after_rename, approve(after_rename, "601")).text(),
            "renaming an implementation file out of the tree does not hide it",
            failures,
        )

        run("git", "reset", "--hard", base)
        put("NOTES.txt", "documentation-only\n")
        unlabeled = commit("documentation-only")
        expect(
            "unclassified" in check(unlabeled, Evidence()).text(),
            "a documentation-only label does not exempt an unclassified file",
            failures,
        )

        # A roster that exists only in the pull request copy cannot approve.
        pulled = dict(policy.approvers)
        expect("stranger" not in pulled, "the checked roster is the baseline roster", failures)

        run("git", "reset", "--hard", base)
        put(".github/workflows/test-approval.yml", "name: Test approval\n")
        gov = commit("change the gate")
        expect("governance reviewer" in check(gov, Evidence()).text(), "a gate change without governance review fails", failures)
        gov_comment = Comment(
            "801",
            "https://example.test/comment/801",
            "governor",
            f"/approve-governance {gov}",
            "2026-11-23T03:00:00Z",
            12,
        )
        gov_record = governance_record(
            policy, gov_comment, "801", gov, [".github/workflows/test-approval.yml"], repo
        )
        gov_run = WorkflowRun(
            "801",
            policy.trusted_workflow,
            "issue_comment",
            "success",
            "gate-comment-801",
            "governor",
            dump_governance(gov_record),
        )
        gov_evidence = Evidence((gov_comment,), (gov_run,))
        expect(check(gov, gov_evidence).status == "passed", "a reviewed governance change passes", failures)
        reviewer_comment = Comment(
            "802",
            "https://example.test/comment/802",
            "reviewer",
            f"/approve-governance {gov}",
            "2026-11-23T03:00:00Z",
            12,
        )
        reviewer_record = dict(gov_record)
        reviewer_record["approval_id"] = f"tg-{gov[:12]}-802"
        reviewer_record["reviewer"] = {"github_login": "reviewer", "name": "Reviewer", "role": "C"}
        reviewer_record["evidence"] = {
            "comment_id": "802",
            "comment_url": reviewer_comment.url,
            "workflow_run_id": "802",
            "comment_body": reviewer_comment.body.strip(),
        }
        reviewer_run = WorkflowRun(
            "802",
            policy.trusted_workflow,
            "issue_comment",
            "success",
            "gate-comment-802",
            "reviewer",
            dump_governance(reviewer_record),
        )
        expect(
            "governance roster" in check(gov, Evidence((reviewer_comment,), (reviewer_run,))).text(),
            "a test approver cannot approve a gate change",
            failures,
        )
        owner_comment = Comment(
            "803",
            "https://example.test/comment/803",
            "owner",
            f"/approve-governance {gov}",
            "2026-11-23T03:00:00Z",
            12,
        )
        owner_record = governance_record(
            policy, owner_comment, "803", gov, [".github/workflows/test-approval.yml"], repo
        )
        owner_run = WorkflowRun(
            "803",
            policy.trusted_workflow,
            "issue_comment",
            "success",
            "gate-comment-803",
            "owner",
            dump_governance(owner_record),
        )
        expect(
            "self-approval" in check(gov, Evidence((owner_comment,), (owner_run,))).text(),
            "governance self-approval fails",
            failures,
        )
        put(".github/workflows/test-approval.yml", "name: Changed\n")
        changed_gate = commit("change the gate again")
        expect(
            "changed after approval" in check(changed_gate, gov_evidence).text(),
            "a gate file changed after review fails",
            failures,
        )
        run("git", "reset", "--hard", gov)
        put("tradingagents/feature.py", "VALUE = 1\n")
        mixed = commit("mix implementation into the gate change")
        expect("does not cover" in check(mixed, gov_evidence).text(), "a governance review does not cover implementation", failures)
        unconfirmed = load_policy(
            baseline.read_text(encoding="utf-8").replace(
                "governance_roster_confirmed: true", "governance_roster_confirmed: false", 1
            )
        )
        expect(
            "no confirmed governance reviewers" in assess(repo, unconfirmed, base, gov, 12, "owner", Evidence()).text(),
            "an unconfirmed governance roster rejects gate changes",
            failures,
        )
        del early, removed, renamed

    if failures:
        print(f"{len(failures)} test-approval self-test(s) failed.")
        return 1
    print("test-approval self-test passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pre-implementation test approval.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("command", nargs="?", choices=("check", "prepare", "publish-failure", "open-check", "finalize", "complete-run"))
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--post", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--message", default="test approval did not complete")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.command == "open-check":
        return run_open_check()
    if args.command == "complete-run":
        return run_complete_from_env()
    if args.command == "finalize":
        return run_finalize(args.message)
    if args.command == "publish-failure":
        return run_publish_failure(args.message)
    if args.command == "prepare":
        return run_prepare_from_env(args.output, args.post)
    if args.command == "check":
        return run_check_from_env(args.publish)
    parser.error("choose check, prepare, or --self-test")
    return 2


if __name__ == "__main__":
    sys.exit(main())
