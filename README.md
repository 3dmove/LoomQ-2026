# LoomQ · 量子接入平权计划 —— 赛题发布包

> SheNicest 2026 夏季千人烈变黑客松 · 正式赛题（选手分发版）

## 包内容

| 文件 / 目录 | 说明 |
|---|---|
| `LoomQ-赛题手册.pdf` | 正式题面（Typst 排版，8 页），用于官网发布与现场分发 |
| `LoomQ-赛题.html` | 题面网页版（零依赖单文件：无 CDN、无外部字体、无框架），可直接作为活动官网赛题页部署 |
| `problem_statement.md` | 题面 Markdown 源，与 PDF 内容一致，便于线上阅读与检索 |
| `LoomQ-赛题.docx` | 题面 Word 版（由 Markdown 源生成，公式为 Word 原生对象），供组委会流转编辑 |
| `starter-kit/` | 选手工具包 v1.0.0：提交清单、纯接口模板、公开自测、容器基线、RISC-V 模拟器、公开电路与上手资料 |

## 重新生成 PDF / Word

排版源不随本包分发。题面有改动时，同步修改 `problem_statement.md` 与仓库根目录的 `typst/main.typ`，然后：

```bash
# PDF（依赖 brew install typst；字体用 macOS 自带 Didot / Baskerville / Songti SC / Menlo）
cd ../typst && typst compile main.typ ../release/LoomQ-赛题手册.pdf

# Word（依赖 brew install pandoc；先把 md 中的 mermaid 图替换为文字流程，再转换）
pandoc <处理后的md> -f markdown -t docx -o release/LoomQ-赛题.docx
```

## ⚠️ 不在本包内的东西

**`official-eval/`（仓库根目录）是评测组内部资产，严禁随本包分发。** 正式评测由组织方父进程在内存中生成用例并持有期望值，不再把隐藏电路或理想分布复制进选手仓库。评测日流程见 `official-eval/README.md`。

## 分发前检查清单

- [ ] `starter-kit/circuits/` 内只有 `bell.qasm` 与 `ghz3.qasm` 两个公开电路（不含 `ideal_distributions.json`）
- [ ] 原样 Starter Kit 的 L1/L2/L3 功能分均为 0
- [ ] `submission.yaml`、`VERSION`、`CHANGELOG.md` 与 `Dockerfile` 已包含
- [x] 《后端能力表》已定稿并放入 starter-kit（`backend_capabilities.md/json`，L2 选后端判定依据，见题面第五节）

> 注：组委会保障（预发 Token、真机降级计分、统一 LLM 额度）暂无法兑现，已从题面全部移除；选手需自行申请本源 API Token 与自备 LLM API。若后续资源到位，可恢复相应承诺并重编 PDF。
