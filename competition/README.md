# LoomQ 提交运营工具

`config.json` 是截止时间和提交边界的唯一事实源。本届不使用预登记队伍名单：每队指定一个 GitHub 提交账号，该账号的用户名就是 Team ID。fork 所有者、Issue 作者和 Team ID 必须是同一账号；其他成员可以作为仓库协作者参与开发。

GitHub Issue 工作流只验证和归档提交，不运行选手代码。截止后在组委会机器上运行：

```bash
GH_TOKEN=... python3 competition/collect_submissions.py \
  --output /intake/loomq-2026
```

Token 需要读取本仓库 Issues 和 Actions Artifacts 的权限。命令会按 GitHub 提交账号选择截止前最后一次有效提交，输出原始归档、`submission/` 评测目录、JSON 清单和 CSV 汇总。
