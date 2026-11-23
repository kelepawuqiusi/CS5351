---
feature_id: "approval-demo-redaction"
requirements:
  - "SEL-TA-NFR-003"
implementation_paths: []
test_files:
  - "tests/member_d_verification/test_approval_demo_redaction.py"
cases:
  - id: "demo-normal"
    kind: "normal"
    expected: "Ordinary research text is preserved."
  - id: "demo-boundary"
    kind: "boundary"
    expected: "Empty text and None remain unchanged without raising an error."
  - id: "demo-error"
    kind: "error"
    expected: "An exception diagnostic retains its type and removes a synthetic password."
  - id: "demo-security"
    kind: "security"
    expected: "Synthetic credentials in nested data are replaced without changing the caller's input."
pass_condition: "All demo tests pass offline; no real credential, portfolio data, model call or product implementation is introduced."
---

# Plan-first test-approval demonstration

This is a test-only change for existing redaction behavior. It does not claim that the existing product implementation was historically pre-approved. The requirement reference is the current local working selection; reconcile it with A's final registry when that handoff is available.

This first commit contains the plan and listed tests only. No product implementation is included. `implementation_paths` is intentionally empty because this demo does not request a product change. Do not interpret passing ordinary pytest checks as human test approval.

An authorized reviewer other than the PR author must approve the full current commit SHA. After the gate deployment is merged, an unapproved demo should fail `test approval`. Both rosters currently contain only `kelepawuqiusi`; a PR authored by that account cannot be self-approved. Do not forge an approval or change authorship merely to evade this rule.
