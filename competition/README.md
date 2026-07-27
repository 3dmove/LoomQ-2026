# LoomQ 提交运营工具

`config.json` 是截止时间和提交边界的唯一事实源，`teams.json` 是可提交队伍名单。开赛前由组委会在 `teams` 中加入：

```json
{
  "team_id": "team-001",
  "github_users": ["alice", "bob"]
}
```

GitHub Issue 工作流只验证和归档提交，不运行选手代码。截止后在组委会机器上运行：

```bash
GH_TOKEN=... python3 competition/collect_submissions.py \
  --output /intake/loomq-2026
```

Token 需要读取本仓库 Issues 和 Actions Artifacts 的权限。命令会为每队选择截止前最后一次有效提交，输出原始归档、`submission/` 评测目录、JSON 清单和 CSV 汇总。
