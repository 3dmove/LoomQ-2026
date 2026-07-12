# LoomQ Starter Kit v1.0.0

本工具包定义参赛提交协议，并提供公开自测。它不包含正式评分器、隐藏答案、Mock 得分路径或任何 Level 的参考解答。

## 提交结构

```text
starter-kit/
├── VERSION
├── CHANGELOG.md
├── submission.yaml
├── adapter.py
├── evaluator.py
├── riscv_emulator.py
├── backend_capabilities.md
├── backend_capabilities.json
├── QUANTUM_101.md
├── gate_identities.md
├── target_ir_contract.md
├── requirements.txt
├── Dockerfile
├── circuits/
│   ├── bell.qasm
│   └── ghz3.qasm
└── examples/
```

提交时，仓库根目录必须保留并填写 `submission.yaml`，同时提供 `adapter.py`。非 Python 项目可以在 `adapter.py` 中通过 `subprocess` 调用自己的 CLI 或二进制。

## 环境

公开 evaluator 只使用 Python 标准库，无需安装依赖。推荐 Python 3.11，与官方基础镜像一致：

```bash
python3 evaluator.py --level l1 --target spinq,originq --json-out report.json
```

参赛项目使用第三方 SDK 时，必须把依赖写入 `requirements.txt` 并精确锁定版本，例如 `package==1.2.3`。不要提交 `package>=1.2`，正式评测不会替参赛队选择依赖版本。

也可以先验证基础容器：

```bash
docker build -t loomq-submission .
docker run --rm loomq-submission
```

## Adapter 契约

L1 必须实现：

```python
def transpile(qasm_str: str, target: str) -> str: ...
def run(qasm_str: str, target: str, shots: int) -> dict: ...
```

`transpile()` 的三个目标格式不是任意字符串，规范子集见 `target_ir_contract.md`。正式评测会由组织方解析并模拟返回的目标 IR。

L2、L3 为可选接口：

```python
def agent_chat(prompt: str) -> str: ...
def compile_hybrid(hybrid_qasm_str: str) -> tuple[list, str]: ...
```

未参赛的 Level 保持 `NotImplementedError`，并在 `submission.yaml` 中标为 `false`。Starter Kit 原样运行会失败，这是预期行为，也确保原样提交不会获得功能分。

## 公开自测

```bash
# 默认只测试 submission.yaml 中声明为 true 的 Level
python3 evaluator.py --json-out report.json

# 单独测试
python3 evaluator.py --level l1 --target spinq,originq,braket
python3 evaluator.py --level l2
python3 evaluator.py --level l3
```

退出码：全部公开测试通过为 `0`，存在失败为 `1`。`report.json` 只表示公开契约自测结果，不是正式分数。

正式评测由组织方在隔离环境运行：每个 case 使用独立进程、私有随机种子和私有期望值；提交进程不会获得理想分布文件。组织方还会分别验证目标原生 IR、真机证据、架构与交互体验。

## 网络与密钥

L1、L3 默认禁止网络。L2 如需 LLM API，必须在 `submission.yaml` 声明，并只列必要域名。不要把 API Key 提交进 Git；正式流程通过环境变量注入，变量名应写在项目 README 中。

## 版本政策

合同版本为 `1.0`。开赛后，`1.x` 只允许增加向后兼容的文档、诊断信息和公开测试，不改变已有接口语义；破坏性修改必须发布新的合同版本并为旧版保留评测通道。
