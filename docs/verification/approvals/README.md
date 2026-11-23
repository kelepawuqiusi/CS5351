# Test-approval archive

Records in this directory are copies of approvals that the trusted test-approval workflow already accepted. A YAML file by itself is not an approval. Copying a record, editing its timestamp, or pointing it at another pull request does not pass the check.

The checker reads the receipt artifact stored by the successful run of `.github/workflows/test-approval.yml`. That receipt is bound to the comment text, commit, and fingerprints accepted at that time. The current comment must still be the same command. Editing it, or deleting it, invalidates that approval. A revocation receipt stays in force if its comment is later deleted. Older receipts already in this directory are left in place; a later pull request is checked only against its own approval id.

The checker rebuilds the record from the protected baseline and the approved commit. The archived file for that approval id must match. Historical work merged before this gate existed is an evidence gap. This repository does not backfill approval records for that work, and this gate does not claim to have retrospectively verified it.

## Completion and activation

`test-approval.yml` stores the producer context and receipt, but never marks an approval green while that run is in progress. `test-approval-complete.yml` handles its `workflow_run: completed` event, checks the actual producer conclusion and retained receipt, and revalidates the current PR and comment state before publishing `test approval`. Ordinary comment rechecks remain separate from receipt production.

Both workflows and the baseline verifier must be on the protected default branch before activation. Member E confirmed `kelepawuqiusi` for both reviewer rosters on 2026-11-23. This account still cannot approve its own PR. A failed, cancelled or unverifiable producer cannot release a PR. If GitHub/API access or artifact retention prevents verification, the check fails or remains incomplete; retry/repair it rather than treating it as approval. No workflow can guarantee a status write after a hard runner termination or an unavailable GitHub API.

Workflow artifacts are required by this verifier even when a YAML copy is archived in the repository. Set artifact retention to cover the lifetime of open PRs; an expired receipt must not be treated as valid approval merely because a YAML copy exists.

## First deployment

The initial gate deployment is bootstrapping infrastructure, not a retrospectively test-approved feature. Keep the existing required checks and human review in place while the team reviews the deployment PR. Do not add `test approval` to branch protection until its workflows have run on GitHub. Any administrator bypass used for initialization needs explicit authorization and must be recorded; the automation does not grant itself that exception.
