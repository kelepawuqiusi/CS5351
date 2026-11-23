# Original conversation — test-approval gate review and corrections

Date: 23 November 2026. Original UTC timestamps below are preserved. The selected user question and public assistant messages are retained verbatim. Tool calls/results, write payloads and internal reasoning are omitted. This snapshot ends before the final reply.

## File-change summary

This follow-up corrected the real-roster-dependent self-test, deferred success until a separate trusted workflow observes producer completion, revalidated receipts/current PR state, and added API-format/commit-binding regression coverage. It preserved the separate governance-review process and left both human rosters unconfirmed. No commit, push or branch-protection change was made.

Current file lengths follow; these are cumulative working-copy lengths, not per-task additions/deletions. Several gate files were already untracked before this follow-up, so no unsupported per-task diff totals are claimed.

- `scripts/ci/check_test_approval.py` — 2295 current lines.
- `.github/workflows/test-approval.yml` — 192 current lines.
- `.github/workflows/test-approval-complete.yml` — 32 current lines.
- `tests/member_d_verification/test_test_approval_completion.py` — 219 current lines.
- `docs/verification/approvals/README.md` — 15 current lines.
- `docs/code-governance/verification-constraints.md` — 378 current lines.

## Verification

- Existing approval self-tests passed, including historical receipts, edited/deleted comments, unlisted tests and governance approvals.
- New lifecycle/API regression tests: 23 passed. Final full offline regression: 1,762 passed, 2 skipped, 1 deselected, 100 subtests passed. The skips are opt-in live semantic replay and the absent optional Bedrock dependency.
- Full-repository Ruff passed. The producer/completion YAML files parsed successfully.
- No GitHub execution, real merge-blocking demonstration or deployment is claimed.

## Original user question and public assistant replies

### User — 2026-11-23T09:45:26.318Z

请检查有没有修复成功，如果没有，请你来修复：这五处都会在启用后挡住正常合并或放过不该过的批准。我先对照检查器和 workflow 的现有判断，再按复现结果改。

五处都是门禁启用后会误放行或误拦截的问题。我先把自测、收据匹配和 workflow 的发布顺序读完，再按复现方式改。

这五处都会在启用后误放行或误拦截。我会把自测和真实名单分开，让收据绑定当时的评论和指纹，并改掉提前标绿的发布顺序。

五处缺陷都已按复现方式修好。本地自测和 Ruff 通过。检查名 `test approval` 仍然没有设为必需检查，也没有提交或推送。

1. **名单不再被自测锁死。** 空名单改成独立样例。真实策略里填入确认过的审批人后，自测仍能通过。
2. **旧运行不能套到新评论。** 检查器读取成功运行保存的收据，并核对该次接受的评论原文、提交和指纹。评论被改成指向新提交会失败；批准评论被删除也会失败。撤回收据在评论删除后仍然有效，不能靠删评论恢复批准。没有这份收据的旧运行不算批准。
3. **历史收据可以共存。** 只核对当前 Pull Request、当前批准编号对应的那一份记录。改动另一份记录仍会失败。
4. **未列入计划的测试不再放行。** 计划列出的测试之外，任何测试或验证脚本变更都会失败。
5. **不再提前标绿。** 处理期间检查保持未完成。收据附件保存并写出评论之后，才发布最终结果。失败或取消会把检查标为失败，未完成的运行不会被当成成功。

治理文件不再是改了就永久失败。策略、检查器和 workflow 的改动需要基线治理审核人使用：

/approve-governance <完整的 40 位提交 SHA>

功能测试的审批人不能代替这次审核，Pull Request 作者也不能批准自己。这类 Pull Request 不能同时改实现或测试。两份名单仍然是空的。启用前要先把第一名治理审核人写进默认分支；之后的门禁修改走这条命令，不需要临时关掉保护。


### Assistant — 2026-11-23T09:45:30.638Z

我会重新检查本地实现，并独立复测这五处缺陷和新增的治理审批流程。若仍有问题，我会直接修复并验证；本次不提交、推送或启用分支保护。


### Assistant — 2026-11-23T09:47:33.822Z

前四处的主要修复已看到，但还有两个残留：自测仍会受真实名单中的具体用户名影响；最后一步发布绿色结果时，整个 workflow 仍未结束，而且没有完整重验收据。我会把最终放行移到“收据 workflow 已成功完成”后的独立验证步骤，并补上对应测试。


### Assistant — 2026-11-23T09:52:46.415Z

残留问题已修正，新增的 20 项回归测试通过。现在收据生成流程不会直接标绿；独立完成流程会确认原运行成功，再核对收据、当前 PR 和评论状态。原来的 37 项自测也通过了，我会继续核对收据归档、治理审批和 workflow 配置。


### Assistant — 2026-11-23T09:59:42.098Z

完整离线回归已通过一次：1,759 项通过，原有两项跳过保持不变。随后核对 GitHub API 格式时，又补了 workflow 路径带 `@main` 后缀的兼容，以及检查结果不能更新到错误提交的校验；相关测试已增至 23 项并全部通过。最后我会更新使用说明和本次 AI 日志，再验证最终版本。

