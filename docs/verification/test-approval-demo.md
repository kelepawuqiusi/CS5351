# 测试批准门：演示 PR 操作说明

## 这次提交包含什么

- `docs/verification/plans/approval-demo-redaction.md`：完整格式的测试计划。
- `tests/member_d_verification/test_approval_demo_redaction.py`：四个离线测试，仅覆盖现有脱敏功能。
- 对应 AI 使用日志。

没有修改产品代码，没有调用真实模型，也没有创建虚假的批准收据。

## 如何查看与操作

1. 查看 PR 的 **Files changed**，先读计划的 YAML 头部，再看四个测试。
2. 在最新提交中复制完整 40 位 SHA。授权审批人必须不是 PR 作者。
3. 授权成员在 PR 评论中输入 `/approve-tests <完整 SHA>`，不要只点赞或使用短 SHA。
4. 等待 **Test approval** 收据流程和 **Complete test approval** 完成流程结束，再看固定检查 `test approval` 的结果。
5. 下载真实生成的收据。若后续有实现，必须在批准后的提交中进行，并在合并前把核对过的收据放入 approvals 目录。
6. 测试计划、测试文件和范围改变时，不要继续使用旧批准。

## 当前演示的限制

门禁启用 PR 合并到默认分支之前，新的检查不会完整生效。启用后，需要重新打开本演示 PR 或推送后续提交来触发检查。

目前两份审批名单都只有 `kelepawuqiusi`。如果本 PR 也是该账号创建，就不能由它自我批准。这个 PR 可展示格式及缺少批准时的阻挡；成功审批示范需要另一名成员发起 PR，或由用户明确增加另一名审批人。

本例是测试-only 的流程演示，不要求给已有产品补造历史批准，也不表示产品需要新增实现才能完成这个演示。

离线运行：`python -m pytest -q tests/member_d_verification/test_approval_demo_redaction.py`。
