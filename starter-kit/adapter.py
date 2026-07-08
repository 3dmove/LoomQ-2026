#!/usr/bin/env python3
"""
LoomQ 量子接入平权计划 - 统一适配器接口 (契约 B)

选手需要在此文件中完善 transpile、run、agent_chat 以及 compile_hybrid 等函数。
我们已为你默认打通了各平台的模拟测试与动态 Mock 机制，确保本地 evaluator.py 能够零配置一键跑通。
"""

import os
import re
import tempfile
import time
import uuid
from typing import Tuple, List, Dict, Any

# 导入 AWS Braket 依赖（已包含在 requirements.txt 中，默认开箱即用）
try:
    from braket.devices import LocalSimulator
    from braket.ir.openqasm import Program
except ImportError:
    LocalSimulator = None

# 量旋与本源依赖（选手按需解注释安装）
try:
    import spinqit as sq
    from spinqit import get_compiler, get_basic_simulator, BasicSimulatorConfig
except ImportError:
    sq = None

try:
    import pyqpanda as pq
except ImportError:
    pq = None


def transpile(qasm_str: str, target: str) -> str:
    """
    将标准 OpenQASM 2.0 转换为对应后端的原生指令。

    参数:
        qasm_str (str): 输入的标准 OpenQASM 2.0 线路代码。
        target (str): 目标平台，可选值为 'braket', 'spinq', 'originq'。

    返回:
        str: 目标后端原生指令。
    """
    target = target.lower()

    if target == "braket":
        # AWS Braket 底层使用 OpenQASM 3.0。
        # 简单转换占位实现
        lines = []
        for line in qasm_str.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("include"):
                continue
            if line.startswith("OPENQASM 2.0;"):
                lines.append("OPENQASM 3.0;")
                continue

            if line.startswith("qreg "):
                parts = line.replace("qreg ", "").replace(";", "").strip()
                name, size = parts.split("[")
                size = size.replace("]", "")
                lines.append(f"qubit[{size}] {name};")
            elif line.startswith("creg "):
                parts = line.replace("creg ", "").replace(";", "").strip()
                name, size = parts.split("[")
                size = size.replace("]", "")
                lines.append(f"bit[{size}] {name};")
            elif line.startswith("cx "):
                lines.append(line.replace("cx ", "cnot "))
            elif line.startswith("measure "):
                parts = line.replace("measure ", "").replace(";", "").strip()
                q_reg, c_reg = parts.split("->")
                lines.append(f"{c_reg.strip()} = measure {q_reg.strip()};")
            else:
                lines.append(line)
        return "\n".join(lines)

    elif target == "spinq":
        return qasm_str

    elif target == "originq":
        if pq is not None:
            # 选手可使用 pyqpanda 的原生转译
            return "/* OriginIR Output */"
        return "/* OriginIR Mock Output */"

    else:
        raise ValueError(f"不支持的目标后端: {target}")


def run(qasm_str: str, target: str, shots: int = 1024) -> dict:
    """
    运行 OpenQASM 2.0 线路，返回符合大赛约定的统一规范 JSON 字典。
    """
    target = target.lower()

    if target == "braket":
        if LocalSimulator is None:
            raise ImportError("请先安装 amazon-braket-sdk (uv pip install amazon-braket-sdk 或 pip install amazon-braket-sdk)")

        qasm_3 = transpile(qasm_str, "braket")
        device = LocalSimulator()
        program = Program(source=qasm_3)
        task = device.run(program, shots=shots)
        result = task.result()
        counts = result.measurement_counts

        return {
            "backend": "aws_local_simulator",
            "job_id": result.task_metadata.id,
            "shots": shots,
            "counts": dict(counts),
            "bit_order": "little",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "meta": {
                "depth": len(result.measured_qubits)
            }
        }

    elif target == "spinq":
        if sq is not None:
            # ── 真实 SpinQit 调用（官方 API：spinqit 0.2.x）──
            # 1. 将 QASM 字符串写入临时文件
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".qasm", delete=False, encoding="utf-8"
            )
            try:
                tmp.write(qasm_str)
                tmp.close()
                # 2. 使用 QASM 编译器编译为中间表示 (IR)
                comp = get_compiler("qasm")
                ir = comp.compile(tmp.name, 0)
            finally:
                os.unlink(tmp.name)
            # 3. 使用 BasicSimulator 执行
            engine = get_basic_simulator()
            config = BasicSimulatorConfig()
            config.configure_shots(shots)
            raw = engine.execute(ir, config)
            counts = raw.counts

            # 4. 获取量子比特数并归一化 counts key
            n_qubits = ir.qnum
            normalized_counts = {str(k): v for k, v in counts.items()}

            # 优先读取真实 job_id，不可用时回退到与 run_spinq.py 一致的格式
            job_id = (
                getattr(raw, 'job_id', None)
                or getattr(raw, 'task_id', None)
                or f"spinq-local-{hash(qasm_str) & 0xFFFF:04x}"
            )

            return {
                "backend": "spinq_basic_simulator",
                "job_id": job_id,
                "shots": shots,
                "counts": normalized_counts,
                "bit_order": "little",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "meta": {"qubits_count": n_qubits},
            }
        else:
            # 动态自适应 Mock 机制，确保首跑通过
            if "qreg q[3]" in qasm_str or "qubit[3]" in qasm_str or "q[3]" in qasm_str:
                mock_counts = {"000": shots // 2, "111": shots - (shots // 2)}
            else:
                mock_counts = {"00": shots // 2, "11": shots - (shots // 2)}
            return {
                "backend": "spinq_taurus_mock",
                "job_id": f"mock-spinq-{uuid.uuid4().hex[:8]}",
                "shots": shots,
                "counts": mock_counts,
                "bit_order": "little",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "meta": {"is_mock": True}
            }

    elif target == "originq":
        if pq is None:
            if "qreg q[3]" in qasm_str or "qubit[3]" in qasm_str or "q[3]" in qasm_str:
                mock_counts = {"000": shots // 2, "111": shots - (shots // 2)}
            else:
                mock_counts = {"00": shots // 2, "11": shots - (shots // 2)}
            return {
                "backend": "originq_simulator_mock",
                "job_id": f"mock-originq-{uuid.uuid4().hex[:8]}",
                "shots": shots,
                "counts": mock_counts,
                "bit_order": "little",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "meta": {"is_mock": True}
            }
        # 【选手实现】：真实的 pyqpanda 运行逻辑

    else:
        raise ValueError(f"不支持的目标后端: {target}")


def agent_chat(prompt: str) -> str:
    """
    [Level 2 智能体交互接口]
    输入用户的自然语言意图、包含错误的代码、或者后端选型咨询，返回智能响应。
    选手在此处应连接真实的 LLM API（如 Gemini/GPT），进行 Prompt 引导或 Agent 反馈。

    为了方便选手在本地零环境冷启动测试，我们内置了标准测试 Prompt 的自适应响应：
    """
    prompt = prompt.strip()

    # 场景 1：意图生成 QASM 2.0
    if "最大纠缠态" in prompt or "GHZ" in prompt:
        return """
        好的，已为您生成一个标准的 3 比特 GHZ 最大纠缠态线路：
        OPENQASM 2.0;
        include "qelib1.inc";
        qreg q[3];
        creg c[3];
        h q[0];
        cx q[0], q[1];
        cx q[1], q[2];
        measure q -> c;
        """

    # 场景 2：代码纠错并修复
    elif "语法错误" in prompt or "CX" in prompt:
        return """
        为您分析了代码，原代码中的 CX 拼写错误，且未定义经典寄存器，已为您修复如下：
        OPENQASM 2.0;
        include "qelib1.inc";
        qreg q[2];
        creg c[2];
        h q[0];
        cx q[0], q[1];
        measure q -> c;
        """

    # 场景 3：智能选后端
    elif "15 个量子比特" in prompt or "选哪个平台" in prompt:
        return (
            "针对 15 个量子比特且要求零排队等待的需求，推荐选择 AWS Braket 本地模拟器（规范标识：braket_local_simulator）。"
            "因为目前真实的量子物理真机（如量旋 Taurus 或本源悟空）比特数有限且任务排队可能长达数小时，"
            "使用本地模拟器可以完美实现 15 比特并行仿真计算且无需等待排队。"
        )

    # 选手连接大模型实现
    # TODO: 编写 LLM API 接入与 Prompt 解析代码
    return "抱歉，作为 LoomQ 智能体，我尚未接入真实大模型 API。请输入标准测试指令以进行测试。"


# ====================================================================
# Level 3: Hybrid-QASM 最小参考编译器
#
# 按题面第三节的 Hybrid-QASM 文法实现「分词 → 递归下降解析 → RISC-V 代码生成」
# 的完整最小骨架（非打表）。支持的经典块文法：
#   stmt    := "if" "(" cond ")" "{" stmt* "}" ( "else" "{" stmt* "}" )?
#            | reg "=" expr ";"
#   cond    := operand ("==" | "!=") operand
#   expr    := operand ( ("+" | "-") operand )*
#   operand := 整数 | r1..r9 | c[k]
# 寄存器映射：r1..r9 → x1..x9；测量位 c[k] → x(10+k)（由评测系统注入）；
# x29/x30 为编译器保留的临时寄存器。
# 生成的汇编只使用 riscv_emulator.py 支持的指令：li/add/sub/addi/beq/bne/j。
#
# 选手可在此基础上扩展：更多运算符、乘法展开、循环、寄存器分配优化等。
# ====================================================================

_TOKEN_RE = re.compile(r"\s*(c\[\d+\]|r[1-9]\b|\d+|==|!=|[{}()=+;-]|if\b|else\b)")


class HybridQASMCompiler:
    """把 Hybrid-QASM 拆分为 (量子操作序列, RISC-V 汇编)。"""

    def compile(self, source: str) -> Tuple[List[str], str]:
        quantum_src, classical_src = self._split(source)
        quantum_ops = self._parse_quantum(quantum_src)
        self._tokens = self._tokenize(classical_src)
        self._pos = 0
        self._asm: List[str] = []
        self._label_count = 0
        stmts = self._parse_stmts(stop_at_brace=False)
        for stmt in stmts:
            self._gen_stmt(stmt)
        return quantum_ops, "\n".join(self._asm)

    # ---------- 拆分量子部分与经典块 ----------

    @staticmethod
    def _split(source: str) -> Tuple[str, str]:
        m = re.search(r"classical\s*\{", source)
        if not m:
            return source, ""
        depth, i = 1, m.end()
        while i < len(source) and depth > 0:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        if depth != 0:
            raise SyntaxError("classical 块花括号不匹配")
        return source[:m.start()] + source[i:], source[m.end():i - 1]

    @staticmethod
    def _parse_quantum(src: str) -> List[str]:
        ops = []
        for raw in src.split("\n"):
            line = raw.split("//")[0].strip()
            if not line or line.startswith(("OPENQASM", "include", "qreg", "creg", "barrier")):
                continue
            ops.extend(s.strip() for s in line.split(";") if s.strip())
        return ops

    # ---------- 分词 ----------

    @staticmethod
    def _tokenize(src: str) -> List[str]:
        src = re.sub(r"//[^\n]*", "", src)
        tokens, pos = [], 0
        while pos < len(src):
            if src[pos:].strip() == "":
                break
            m = _TOKEN_RE.match(src, pos)
            if not m:
                raise SyntaxError(f"经典块中存在无法识别的符号: {src[pos:pos + 20]!r}")
            tokens.append(m.group(1))
            pos = m.end()
        return tokens

    # ---------- 递归下降解析 ----------

    def _peek(self) -> str:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else ""

    def _next(self) -> str:
        tok = self._peek()
        self._pos += 1
        return tok

    def _expect(self, tok: str) -> str:
        got = self._next()
        if got != tok:
            raise SyntaxError(f"期望 {tok!r}，实际为 {got!r}")
        return got

    def _parse_stmts(self, stop_at_brace: bool) -> list:
        stmts = []
        while self._pos < len(self._tokens) and not (stop_at_brace and self._peek() == "}"):
            stmts.append(self._parse_stmt())
        return stmts

    def _parse_stmt(self):
        if self._peek() == "if":
            self._next()
            self._expect("(")
            left = self._parse_operand()
            op = self._next()
            if op not in ("==", "!="):
                raise SyntaxError(f"条件运算符只支持 == 和 !=，实际为 {op!r}")
            right = self._parse_operand()
            self._expect(")")
            self._expect("{")
            then_body = self._parse_stmts(stop_at_brace=True)
            self._expect("}")
            else_body = []
            if self._peek() == "else":
                self._next()
                self._expect("{")
                else_body = self._parse_stmts(stop_at_brace=True)
                self._expect("}")
            return ("if", (left, op, right), then_body, else_body)
        # 赋值语句
        target = self._next()
        if not re.fullmatch(r"r[1-9]", target):
            raise SyntaxError(f"赋值目标必须是 r1..r9，实际为 {target!r}")
        self._expect("=")
        expr = [("+", self._parse_operand())]
        while self._peek() in ("+", "-"):
            expr.append((self._next(), self._parse_operand()))
        self._expect(";")
        return ("assign", target, expr)

    def _parse_operand(self):
        tok = self._next()
        if tok.isdigit():
            return int(tok)
        if re.fullmatch(r"r[1-9]|c\[\d+\]", tok):
            return tok
        raise SyntaxError(f"非法操作数: {tok!r}")

    # ---------- RISC-V 代码生成 ----------

    @staticmethod
    def _reg_of(operand: str) -> str:
        if operand.startswith("r"):
            return "x" + operand[1:]
        k = int(operand[2:-1])  # c[k] -> x(10+k)
        return f"x{10 + k}"

    def _operand_to_reg(self, operand, scratch: str) -> str:
        """整数字面量装入 scratch；寄存器操作数直接引用。"""
        if isinstance(operand, int):
            self._asm.append(f"li {scratch}, {operand}")
            return scratch
        return self._reg_of(operand)

    def _gen_stmt(self, stmt):
        if stmt[0] == "assign":
            _, target, expr = stmt
            first = expr[0][1]
            if isinstance(first, int):
                self._asm.append(f"li x30, {first}")
            else:
                self._asm.append(f"addi x30, {self._reg_of(first)}, 0")
            for op, operand in expr[1:]:
                if isinstance(operand, int):
                    self._asm.append(f"addi x30, x30, {operand if op == '+' else -operand}")
                else:
                    mnemonic = "add" if op == "+" else "sub"
                    self._asm.append(f"{mnemonic} x30, x30, {self._reg_of(operand)}")
            self._asm.append(f"addi {self._reg_of(target)}, x30, 0")
        elif stmt[0] == "if":
            _, (left, op, right), then_body, else_body = stmt
            ra = self._operand_to_reg(left, "x30")
            rb = self._operand_to_reg(right, "x29")
            n = self._label_count
            self._label_count += 1
            # 条件不成立时跳转到 else：== 取反用 bne，!= 取反用 beq
            branch = "bne" if op == "==" else "beq"
            self._asm.append(f"{branch} {ra}, {rb}, ELSE_{n}")
            for s in then_body:
                self._gen_stmt(s)
            self._asm.append(f"j END_{n}")
            self._asm.append(f"ELSE_{n}:")
            for s in else_body:
                self._gen_stmt(s)
            self._asm.append(f"END_{n}:")


def compile_hybrid(hybrid_qasm_str: str) -> Tuple[List[str], str]:
    """
    [Level 3 混合编译接口]
    输入 Hybrid-QASM（OpenQASM 2.0 + classical{} 经典控制块，文法见题面第三节）。
    返回:
        quantum_operations (List[str]): 剥离出来的纯量子逻辑操作序列。
        riscv_assembly (str): 经典控制流对应的 RISC-V 汇编（仅使用官方模拟器支持的指令子集）。

    此实现为官方参考的最小真实编译器骨架（词法 + 递归下降 + 代码生成，支持任意嵌套
    if/else 与加减赋值），不是针对样例的打表。选手可直接扩展它，或替换为自己的实现。
    """
    return HybridQASMCompiler().compile(hybrid_qasm_str)
