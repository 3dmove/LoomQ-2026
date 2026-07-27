# LoomQ · 量子接入平权计划：赛题发布包

> SheNicest 2026 夏季千人烈变黑客松 · 正式赛题（选手分发版）

## 包内容

| 文件 / 目录 | 说明 |
|---|---|
| `LoomQ-赛题手册.pdf` | 正式题面（Typst 排版，8 页），用于官网发布与现场分发 |
| `LoomQ-赛题.html` | 题面网页版（零依赖单文件：无 CDN、无外部字体、无框架），可直接作为活动官网赛题页部署 |
| `problem_statement.md` | 题面 Markdown 源，与 PDF 内容一致，便于线上阅读与检索 |
| `LoomQ-赛题.docx` | 题面 Word 版（由 Markdown 源生成，公式为 Word 原生对象），供组委会流转编辑 |
| `starter-kit/` | 选手工具包 v1.1.0：提交清单、L2 环境协议、公开自测、容器基线、RISC-V 模拟器、公开电路与上手资料 |

## 常见问题

### 需要提前登记队伍名单吗？

不需要。每队指定一个 GitHub 提交账号，该账号的用户名就是本次比赛的 Team ID。fork 必须归该账号所有，最终提交 Issue 也必须由同一账号创建。

### 多人团队如何协作？

其他成员可以作为 fork 仓库的 collaborator、通过分支或 Pull Request 参与开发。只有最终提交动作需要由指定的 GitHub 提交账号完成。

### 正式提交的内容放在哪里？

统一放在 fork 的 `starter-kit/` 中。组委会只把该目录提取为正式评测根目录。

### 提交前要运行什么？

在 fork 根目录运行：

```bash
python3 starter-kit/prepare_submission.py --team-id <GITHUB_USERNAME>
```

预检会确认工作区干净、HEAD 已推送、fork 所有者与 Team ID 一致，并输出可填写到 Issue Form 的仓库地址和 40 位 commit SHA。

### 如何确认提交成功？

最终提交 Issue 获得 `submission:accepted` 标签，并出现包含 commit、归档 SHA-256 和 Artifact ID 的自动回执，才算有效提交。仅创建 Issue 或通过本地预检不代表提交成功。

### 提交后还能更新吗？

可以。修改代码并 push 后重新创建一个最终提交 Issue，不要编辑旧 Issue。截止前最后一次通过校验的提交生效。

### 截止时间如何判定？

截止时间是 **2026-08-25 12:00 UTC+8**，以 GitHub 服务器记录的 Issue `created_at` 为准，不看 commit 时间或本地电脑时间。

### L2 会提前提供组委会 API 或 Key 吗？

不会。赛前可使用自己的 DeepSeek Key 或其他 OpenAI-compatible 服务调试，但代码必须读取 `LOOMQ_LLM_*` 环境变量。正式评测由组委会统一注入 DeepSeek 模型服务和调用预算。

### 可以依赖其他外部 API 吗？

不建议。正式评测环境不保证能够访问模型服务以外的外部网络地址。

### fork 或分支在截止后被删除怎么办？

每次有效提交都会即时归档为 GitHub Actions Artifact。组委会截止后从归档收集，不依赖 fork 在评分时仍然存在；选手仍应保留 fork 便于复核。
