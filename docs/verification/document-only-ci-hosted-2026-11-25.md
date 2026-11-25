# Hosted document-only CI verification — 25 November 2026

Scope: verify the lightweight PR route introduced by PR #52, not application or live-model acceptance. This PR changes documentation only. Worker skips must be explicit, and every fixed required name must still report the document-validation outcome.

## Negative probe (temporary)

The following deliberately missing local target must make document validation and all seven required summaries fail. No project dependency installation or code tests should run:

[Deliberately broken validation target](missing-document-ci-negative-probe.md)

This temporary link will be replaced with a real repository target after observing the failure. A failed probe is not claimed until the hosted result is inspected. Final evidence will distinguish the failing revision from the corrected one.
