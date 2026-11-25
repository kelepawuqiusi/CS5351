# Static typing and safety checks — coverage and limits

Date: 2026-11-25 (Asia/Hong_Kong). Test-plan pre-approval remains paused as a required check. These checks do not restore it.

## Current required checks and execution routes

The seven configured names are `required tests`, `ruff (strict, full repo)`, `dependency check`, `ai-log updated`, `requirements schema`, `type check` and `security checks`. All seven fixed-name summaries report on every PR. Their tools actually run on the full route (protected/mixed/unknown changes and main/version pushes). Pure-document PRs instead require successful classification and document validation, with exactly intentional skips for full-only workers; no package installation, audit, type scan or code-test execution is claimed from that route. See [document-only CI](document-only-ci.md). `classify changes` and `document validation` are supporting jobs, not additional required gates. Static-analysis workers are not extra application stages. The six course gate categories must not be inferred by counting workflow jobs or check names.

## Type coverage

`python -m mypy --config-file pyproject.toml` checks all files in `src/tradingagents/runapi/`, plus `portfolio.py`, `agents/schemas.py` and `agents/rating.py`: currently 15 files. Function bodies without annotations are checked where mypy can infer types. In-scope errors block; there is no in-scope error baseline or ignore-all override. Imported legacy modules use `follow_imports=silent`; missing third-party typing is tolerated. This is incremental typing, not strict typing of the whole repository.

An initial exploratory scan of all 105 application files reported 187 errors in 38 files. Broad legacy/CLI/vendor typing remains a backlog rather than being silently marked fixed. Nine errors in the selected boundary were addressed through precise literal aliases/annotations and narrowing optional values. Runtime formats and existing valid-input behavior are retained. Real mypy fixtures accept `COMPLETED` and reject both an unknown outcome and an integer outcome. The type job targets Python 3.12, matching its CI interpreter and current NumPy dependency stubs; runtime compatibility on Python 3.11–3.14 remains covered by the regression matrix.

## Contract and API surface coverage

- `tests/member_c_verification/offline/test_fr003_validation_freeze.py`: input shape, finite numbers, dates, source immutability and freezing.
- The remaining Member C offline suite: explicit consent, mode propagation, rating/provenance/output contracts, typed failures, events, durable publication, privacy, layering and evaluation populations.
- `docs/code-governance/public-api-contract.json` and `test_security_gate_boundaries.py`: explicit runapi exports, run entry parameter names/kinds/defaults and RunResult fields. Drift fails until deliberately reviewed and the snapshot updated. Snapshot changes trigger the AI-log gate.
- The new unconfirmed-input probe proves no graph factory dispatch occurs before consent. Tests are scripted and do not call a paid model.

This API snapshot covers the documented Python boundary, not every private helper or third-party API. It does not automatically approve intentional breaking changes or prove arbitrary generated text is semantically valid.

## Security scan and fixes

`check_security_scan.py` runs Bandit on all application Python under `src/tradingagents/`, `src/cli/` and `src/demo/` (currently 115 files), blocks medium/high findings, rejects scanner/parse errors and incomplete coverage, and retains the report as a GitHub artifact. Low-severity findings are not blocking and their counts remain in the report. CI/helper scripts are not part of this Bandit application scan; their permission/report behavior is tested separately.

Initial findings were triaged rather than globally suppressed:

- Untrusted Reddit XML now uses `defusedxml`, catches its rejection safely, and has an entity-expansion negative fixture.
- Reddit/StockTwits initial URLs must use their fixed HTTPS hosts with no embedded user credentials before dispatch. Synthetic file/HTTP/foreign-host endpoints are rejected with zero opens. The two precise `B310` suppressions apply only to these guarded urlopen statements; new/blanket suppressions fail the wrapper. This initial-URL policy is not a claim of a complete redirect/DNS security sandbox.
- Checkpoint cleanup uses two literal SQL statements and bound thread IDs instead of interpolating a fixed table name. Existing checkpoint tests verify behavior.
- The market prompt was a scanner false positive because a fixed instruction contained SQL-like words in string concatenation. Separating the unchanged literal from concatenation removes the false positive; a local comparison confirmed the assembled prompt text is identical. No financial instruction or token-optimization target was rewritten.

The scanner also has a real planted shell-injection fixture, and report probes reject empty output, missing scanned files and reported parse errors. A zero scanner exit alone is insufficient to establish a valid scan.

## Permission boundaries

- The PR CI workflow explicitly grants `contents: read`, inherited by its ordinary jobs. `check_workflow_permissions.py` rejects write tokens for PR-code jobs and validates all committed workflows, currently five.
- Privileged comment/workflow-run/target jobs must explicitly check out this repository's trusted default branch. A PR-head checkout, foreign-repository checkout or direct event-expression interpolation into shell code is rejected. Existing receipt workflows retain only their necessary check/comment write scopes.
- Discovery/symlink exclusions, explicit consent, immutable selected input, staging path protections, redaction, sink privacy and terminal visibility are covered by Member C, Member D and Member B offline regressions. Explicit user-selected external portfolio paths remain supported; they are not confused with automatic directory discovery.

**Permission scope:** a local role-permission package now exists; use the [current activation and evidence guide](opencode-permissions.md). Its recorded native probes remain tied to their original revisions, and later path updates are not fresh per-member acceptance. CI token checks do not establish OS-level isolation or universal enforcement of human-only writes. They also do not make PR-controlled workflow code tamper-proof against an authorized member deliberately weakening CI. Pre-approval and live semantic acceptance remain separate.

## Reproduce

Install `pip install -e ".[dev]"`, then run:

```sh
python -m mypy --config-file pyproject.toml
python scripts/ci/check_workflow_permissions.py
python scripts/ci/check_security_scan.py
python -m pytest -q tests/member_d_verification/test_type_gate.py tests/member_d_verification/test_security_gate_boundaries.py
```

The CI security job additionally runs the named Member C offline suite and existing privacy, redaction, replay-durability, terminal-visibility, layering and RSS/StockTwits regressions. The normal full regression job remains intact. No token budget, model, live evaluation rubric or test-approval protection setting is changed.

## Course-layout integration update

Canonical tests are under test/offline and test/live; historical tests/ references remain compatibility aliases. The current source helper resolves the checkout root after package movement. Native role-permission snapshots remain tied to their recorded old hashes; equivalent path updates are not a fresh native-tool acceptance.
