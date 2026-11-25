# Hosted document-only CI verification — 25 November 2026

The CI routing implementation was delivered through [PR #52](https://github.com/kelepawuqiusi/CS5351/pull/52) and merged into main. All seven fixed required checks passed on that implementation PR, which took the full route because it changed workflow and scripts. Local verification recorded 40 focused cases and 2,074 passed regressions, with two skips, one deselection and 100 passed subtests. This is not live-model or independent semantic acceptance.

## Observed negative probe

[PR #53](https://github.com/kelepawuqiusi/CS5351/pull/53), revision `627daaf`, changed only this Markdown document and intentionally included a missing local target. The [hosted CI run](https://github.com/kelepawuqiusi/CS5351/actions/runs/45646260315) completed with successful classification, failed document validation and failed results for all seven fixed required names. Full-only workers (application tests, clean install, dependency audit, Ruff, type, schema and security) were skipped. The PR was blocked. No successful code test or audit execution is claimed from those skips.

## Corrected document

The deliberate bad link has been replaced with the real [submission contents and build guide](../submission/contents-and-build.md). This correction is documentation only. The user requested that further active checking stop and the key changes be submitted, so the corrected revision is pushed without further local tests, hosted-result polling or acceptance claims. GitHub may run its configured CI automatically; a successful corrected run has not been asserted here.

## Delivered behavior

Pure-document PRs validate document formats, local links and applicable report/index consistency without installing project dependencies or running code tests. Mixed, protected and unknown changes retain complete CI; main/version pushes also retain complete checks. The seven branch-protection names are preserved through strict summaries. A document-route pass means the applicable document route succeeded, not that skipped application tools ran. External link destinations, heading fragments, complete PDF layout and semantic truth remain outside the lightweight validator.
