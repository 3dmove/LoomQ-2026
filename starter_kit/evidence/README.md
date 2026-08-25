# LoomQ 人工评分证据

这份文件是人工评分材料的统一入口。请直接编辑它，只填写要申报的项目。截图、原始结果或图表统一放在 `starter_kit/evidence/files/`，也可以引用 `starter_kit/` 中已有的代码和文档。

证据包是可选的。没有申报某项人工分时，留空即可，不影响自动评分。

## 提交前填写

把要申报项目的方框改成 `[x]`，并填写对应内容：

- [x] L1 真机
- [x] L2 交互体验
- [x] 工程与产品化
- [ ] 自定义量子 RISC-V Bonus
- [ ] 新手引导与视觉叙事 Bonus

## L1 真机

每个有效真机平台计 5 分，最多两个平台。模拟器不计真机分。每个平台复制并填写一次下面的信息：

```text
平台名称：spinq
平台 job ID：G-260825-0001, G-260825-0005
运行时间：2026-08-25 01:35:12(北京时间), 2026-08-25 01:55:21
shots：[填写]
实际执行的 QASM：Bell.qasm
平台返回的原始结果：[填写仓库内路径]
任务页截图：evidence/files/spinq_cloud_result_0001.png, spinq_cloud_result_0002.png
```

建议把文件放进 `evidence/files/`，比如：

```text
evidence/files/spinq-circuit.qasm
evidence/files/spinq-result.json
evidence/files/spinq-screenshot.png
```

工作人员会核对 job ID、运行时间、电路、shots 和原始结果。截图只能辅助说明，不能代替 job ID 和原始结果。

## L2 交互体验

请填写：

```text
启动界面或 CLI 的命令：[python starter_kit/adapter.py]
测试入口或页面地址：[无（命令行交互）]
适合现场体验的 3 个用户任务：
1. [输入"生成一个 GHZ 态"，验证是否能输出标准 OpenQASM 2.0 代码]
2. [输入"推荐一个后端运行 15 比特电路"，验证是否能推荐合适的后端]
3. [输入"帮我修复 H q[0]; CX q[0] q[1]"，验证是否能纠正语法错误]
截图或演示视频：[无]
```

工作人员会在组委会统一模型环境中运行最终代码，测试新手是否看得懂、出错后能否得到有效帮助、结果是否清楚，以及多轮回答是否一致。选手自己的对话截图只用于说明产品流程，不直接证明得分。

## 工程与产品化

已有内容可以直接引用主 README 或其他项目文档，不必复制到本目录。

```text
干净环境中的构建和启动命令：[
# 环境 1：Braket + OriginQ（推荐使用 .venv310）
python -m venv .venv310
.venv310\Scripts\activate
pip install -r starter_kit/requirements.txt
python starter_kit/adapter.py  # 启动交互模式

# 环境 2：SpinQ（conda 环境）
conda create -n spinqit_clean python=3.10
conda activate spinqit_clean
pip install spinqit==0.2.4 antlr4-python3-runtime==4.9.3
python starter_kit/adapter.py]

架构说明：[
见 starter_kit/adapter.py 中的函数定义
- transpile(qasm_str, target)：将 OpenQASM 2.0 转译为目标后端 IR
- run(qasm_str, target, shots)：执行电路并返回统一 Schema 结果
- agent_chat(prompt)：L2 智能体，支持自然语言生成电路、纠错、后端推荐
- _apply_gate_decomposition(qasm)：门分解（ccx/swap/相位门展开）]

目标用户和使用场景：[面向无量子计算背景的科研人员、算法工程师和学生，通过自然语言生成量子电路，无需学习各平台SDK]

完整使用流程：[
1. 按上述命令配置环境
2. 设置 DeepSeek API 环境变量（LOOMQ_LLM_BASE_URL、LOOMQ_LLM_API_KEY、LOOMQ_LLM_MODEL）
3. 运行 python starter_kit/adapter.py 进入交互模式
4. 输入自然语言问题（如"生成一个贝尔态"），获得 QASM 代码或后端推荐
5. 输入 exit 退出]
```

工作人员会按最终 commit 实际构建和启动，并检查文档与代码是否一致、产品是否真的降低了量子计算的使用门槛。

## 自定义量子 RISC-V Bonus

以下三项必须齐全且测试通过，才获得 8 分：

```text
指令编码规格：[填写文档路径]
模拟器扩展实现：[填写代码路径]
端到端测试命令：[填写命令或文档路径]
```

## 新手引导与视觉叙事 Bonus

请填写已有材料的路径，不要求为评分另写一套文档：

```text
零基础首次运行指南：[填写]
量子概念解释：[填写]
结果可视化：[填写]
错误恢复或无障碍引导：[填写]
```

以上四项各 1 分。普通项目 README 完整不代表自动获得 Bonus。

## 提交规则

- 所有材料都要在截止前进入最终提交的 commit，工作人员不接受截止后补交。
- 外部视频可以用稳定只读链接，源码、原始结果和复现命令应保存在仓库中。
- 整个 fork commit 的归档包不得超过 100 MiB。
- 不要提交 API Key、Token、Cookie、个人身份信息或平台账户隐私。
- 如申报 L1 真机分，在最终提交 Issue 的 `Hardware evidence` 中填写 `starter_kit/evidence/README.md`。
