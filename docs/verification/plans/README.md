# Test-plan format

One pull request carries one plan. A small change to an existing behaviour can use a short plan; it does not need to restate the whole project.

Save the plan as `docs/verification/plans/<feature-id>.md`. The checker reads the YAML front matter below. Prose after the front matter is for reviewers and is not a substitute for those fields.

```markdown
---
feature_id: "portfolio-note"
requirements:
  - "REQ-TA-FR-001"
implementation_paths:
  - "tradingagents/portfolio.py"
test_files:
  - "tests/test_portfolio_note.py"
cases:
  - id: "normal-flat"
    kind: "normal"
    expected: "An explicit empty portfolio stays flat."
  - id: "boundary-missing"
    kind: "boundary"
    expected: "Missing holdings stay unknown."
  - id: "error-bad-input"
    kind: "error"
    expected: "Invalid input finishes incomplete."
  - id: "security-injection"
    kind: "security"
    expected: "Injected text does not change the published status."
pass_condition: "All four expectations hold and the listed tests pass."
---
```

`implementation_paths` lists the product, prompt, model, dependency, or execution files this feature will change after approval. Leave it empty only when the pull request changes tests or verification scripts and does not change those paths.

Every plan needs at least one `normal`, `boundary`, `error`, and `security` case. Each case needs its own expected result and the plan needs one pass condition.
