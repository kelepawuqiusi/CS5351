> Current layout supplement, 2026-11-25: physical code is under src/tradingagents, src/cli, src/demo; physical tests under test/offline and test/live. Historical root names below remain compatibility aliases to that one source. See [layout and delivery status](../submission/delivery-checklist-2026-11-25.md).

# Structural constraints

Local E5 supplement, 2026-11-25: the [role permission package](opencode-permissions.md) now supplies explicitly loaded, native-tool-tested local permissions. Historical baseline statements below remain scoped to their reference snapshot. This is not OS access control or a new CI gate.

Status: as-built governance consolidation, 2026-11-25 (Asia/Hong_Kong).
Source baseline: main `14b06a5`. This document specifies module restrictions and how they are checked; it does not certify independent acceptance or introduce a new merge gate. Recheck source and CI when the baseline changes.

## Authority and scope

Read the root [AGENTS.md](../../AGENTS.md) first. The canonical [architecture blueprint](../../architecture-blueprint.md), B's [interface contracts](../architecture/interface-contracts.md), [invariants](../architecture/invariants.md) and [runtime policies](../architecture/runtime-policy-catalog.md) supply the design. This file consolidates structural obligations against the existing source layout; it does not replace those contracts or adopt the proposed requirement registry. B's `INV-*`, historical `SEL-TA-*` and candidate `REQ-TA-*` identifiers must be mapped by meaning, not numeric suffix.

“Automated” below means the named checker exists and is wired into the current CI. It is not a claim that arbitrary equivalent violations or dynamic imports are detected. Behavioral tests verify selected boundary effects, not every possible implementation. “Review” means a required review expectation without a complete automated enforcer.

## As-built module map

- `cli/`: terminal selection, confirmation and presentation adapters; `input_ui.py` owns portfolio discovery/consent interaction. Other existing CLI modules can contain CLI interaction.
- `tradingagents/runapi/`: shared noninteractive execution boundary, input freezing, result types, deterministic checks, finalization, report projection, publication, events and redaction.
- `tradingagents/graph/`: engine construction, execution/propagation and checkpoint orchestration.
- `tradingagents/agents/`: analysts, researchers, managers, trader, risk debate, tools, structured output and intermediate context.
- `tradingagents/dataflows/`: routing, dates, symbols, network/file support and vendor adapters under `vendors/`.
- `tradingagents/llm_clients/`: model/provider clients, factory, capabilities and validation. `tradingagents/memory/` owns memory/reflection/settlement services.
- `tradingagents/portfolio.py`: portfolio value models and existing loader. `tradingagents/reporting.py` and `report_html.py`: body rendering, used with the runapi envelope/publication boundary.
- `tests/`: regression, developer probes and independently authored verification, with their provenance preserved. `scripts/ci/` and `.github/workflows/`: governance checks and automation, outside application runtime stages.

These are responsibility boundaries, not a claim of a strict acyclic layering across every package. Existing graph-to-reporting, agent-to-dataflow and memory/client dependencies must be considered before adding an import ban.

## SC-01 — Shared entry and dependency direction

The supported application path is `cli -> runapi -> engine/agents/portfolio/reporting`, with data and model access delegated to their service packages. `runapi` must not import `cli`. Shared execution, agents and graph code must remain usable without terminal input: no `input()` or imports of the prompt modules listed in the layering test. CLI adapters must not duplicate or bypass confirmation, finalization and publication authority.

The supported entry is `run_analysis_api(...)` in `runapi/execution.py`. Root `main.py` and raw graph primitives are legacy/reduced-coverage paths; their availability does not establish full application-contract coverage. Do not run root `main.py` as an import smoke check: it can dispatch real model calls.

Enforcement: [C's layering tests](../../tests/member_c_verification/offline/test_nfr005_layering.py) statically inspect `runapi/`, `agents/` and `graph/` for listed prompt imports and direct `input()` calls, and inspect `runapi/` for `cli` imports. They run in the regression suite and the `security checks` job. Review still checks adapter behavior, additional prompt libraries, aliases, dynamic imports and unscanned packages. No global cycle checker is installed.

## SC-02 — Data/vendor boundary

Third-party vendor-library access belongs in `dataflows/`. Agent tools may call dataflow services, including the existing `dataflows.vendors.yahoo.snapshot` wrapper; that is not the same as importing `yfinance` directly into an agent. New direct vendor-library calls outside the data layer must not be introduced. Preserve typed unavailable/no-data distinctions and analysis-date handling when changing a wrapper.

Enforcement: [test_layering.py](../../tests/test_layering.py) parses application/CLI imports and rejects `yfinance` outside `tradingagents/dataflows/`. It runs in both full regression and security checks. Its vendor set currently contains only `yfinance`: other vendor libraries, raw HTTP, dynamic imports and wrapper bypasses require review. Expanding the automated list requires checking legitimate existing uses and adding appropriate negative probes; do not claim the current test enforces every vendor dependency.

## SC-03 — Input, consent and immutable context

`input_service.py` owns discovery/validation/freezing; `context.py` owns immutable run identity, normalized-content SHA-256 and defensive portfolio copies. Discovery is limited to direct-child regular JSON files with symlink exclusion. An explicitly selected external file remains supported without scanning its parent. Execution must reject unconfirmed context before graph dispatch. Downstream modules must consume the frozen snapshot rather than reread portfolio files or derive trusted provenance from model state. `NO_PORTFOLIO` is unknown holdings, distinct from an explicitly empty portfolio.

Enforcement: the [Member C offline suite](../../tests/member_c_verification/offline) includes discovery, consent, validation/freezing and propagation tests. [Security boundary probes](../../tests/member_d_verification/test_security_gate_boundaries.py) additionally test zero dispatch for unconfirmed input. These are behavioral checks in CI; there is no general import/file-access sandbox preventing all rereads. Review is required for new consumers and alternative entry points.

## SC-04 — Result and deterministic authority

`result.py` defines the public result shape; `checks.py` owns deterministic Q1–Q4 findings; `finalize.py` owns coherent outcome/stop-reason/rating combinations. Model prose must not assign authoritative check outcomes or override trusted metadata. `runapi/reporting.py` projects the checked body and trusted envelope through the rendering modules. Any new output route must preserve the same authority and consistency rules.

Enforcement: C's output/provenance/failure tests, plus the [public API snapshot](public-api-contract.json) and its security-boundary test, cover selected contracts. The API snapshot checks public exports, entry parameters/kinds/defaults and result fields; it does not freeze every private helper. Intentional public-contract changes require explicit review and coordinated fixture/document updates. A Q1–Q4 pass is not factual or semantic certification.

## SC-05 — Publication, events and privacy sinks

`persist.py` owns run-isolated staging/publication and manifests; `events.py` owns structured events; `redact.py` supplies central sanitization. New report/log/event/warning paths must not leak credentials or raw holdings, overwrite input portfolios, escape the chosen artifact area, or publish contradictory outcomes. Preserve the documented distinction between critical publication failure and best-effort event delivery. Do not move these responsibilities into prompts or independently recompute provenance at each sink.

Enforcement: C's privacy, events and persistence tests, D's redaction/regression tests and B's logging/replay/terminal remediation probes run in the security job. The [coverage guide](types-and-security-coverage.md) describes the exact suite. Coverage is fixture-based, not a proof that every future sink is safe. Review must enumerate any newly introduced sink and its failure paths.

## SC-06 — Model, memory and budget extensions

Provider construction and capability handling belong in `llm_clients/`; engine orchestration belongs in `graph/`; memory services belong in `memory/`. Keep model dispatch auditable when adding plain, tool-bound, structured, retry, fallback or reflection paths. Do not invent a universal current prohibition on direct model invocation: existing agents and memory code participate in these paths.

B's extended evidence/checker and call/token-admission contracts include proposed modules and behavior. At this baseline, those proposals must not be described as implemented admission controls or a universally enforced token ceiling. Any implementation needs coordinated changes across dispatch seams, result/finalization/reporting and verification, following the relevant ADR/contracts. Current measurement and concise-context optimization alone do not satisfy a hard-budget requirement. Enforcement here is architecture/code review and the applicable existing regressions; no complete dispatch-dependency or token-admission structural checker exists.

## SC-07 — Governance and automation boundary

Application code must not import CI scripts as runtime services. Tests/governance artifacts must not be represented as application stages. CI jobs executing PR code use read-only repository permissions; privileged target/comment workflows must use trusted baseline code and avoid executing untrusted PR code. New dependencies require the existing dependency review/audit process. Changes to important paths require an AI-log update.

Enforcement: [workflow permission checker](../../scripts/ci/check_workflow_permissions.py), [dependency checker](../../scripts/ci/check_dependencies.py), [AI-log checker](../../scripts/ci/check_ai_log_updated.py) and their probes are wired into CI. The application-to-CI import prohibition is a review rule, not a complete installed import checker. The [security coverage guide](types-and-security-coverage.md) describes scanner and privilege limits. OpenCode role ACLs and human-only file-write enforcement are not deployed; ownership instructions in AGENTS.md do not create filesystem permissions.

## Required verification and change expectations

For a structural code change, run the affected behavioral tests and these existing layering checks from the repository root:

```sh
python -m pytest -q tests/test_layering.py tests/member_c_verification/offline/test_nfr005_layering.py
```

Use the commands in [AGENTS.md](../../AGENTS.md) for the full applicable regression, lint, incremental typing, schema and safety checks; use the workflow's declared development dependencies. Mypy currently scopes 15 boundary/portfolio/output files and is not a whole-project dependency checker. Bandit scans application/CLI Python for the configured security findings, not architectural correctness. A checker must fail on its documented violation; do not weaken a test or suppress a finding to hide a boundary breach.

At this baseline the required check names are `required tests`, `ruff (strict, full repo)`, `dependency check`, `ai-log updated`, `requirements schema`, `type check` and `security checks`. These seven names are fixed summaries: full-route workers execute the tools, while classified pure-document PRs require document validation and intentional worker skips. `classify changes` and `document validation` are auxiliary jobs, not extra required gates. See [CI routing](document-only-ci.md). Live branch protection, not this document, determines enforcement. Test-plan pre-approval remains paused as a required merge check by user instruction; this file does not reactivate it. A live semantic gate is not installed as a default required check.

For an intentional boundary change, record the reason and affected modules, consult B's design/ADR and C's verification contracts, update relevant documentation/fixtures/API snapshots, and retain evidence of the applicable checks. User authorization and cross-role exceptions follow AGENTS.md. B verifies architecture interpretation, D the actual implementation links, C independent acceptance, and E governance integration. This consolidation is not their approval receipt.

## Known enforcement gaps

- No complete allowed-import matrix, cycle detection or dynamic-import/control-flow analysis.
- Prompt/library restrictions cover named modules and patterns in named directories; vendor import enforcement currently names only `yfinance`.
- Input, publication and sanitization controls have concrete components and behavioral probes, but no universal runtime filesystem/network sandbox.
- Role-specific coding-agent ACLs, live semantic acceptance and proposed extended budget/evidence mechanisms are not established by this document.

These gaps must remain visible. They do not prevent delivery of this structural specification; closing one requires a separate scoped implementation with reproducible verification, not a stronger claim in prose.
