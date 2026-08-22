#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LoomQ adapter supporting Braket (braket), OriginQ (originq), and SpinQ (spinq)."""
import re
from datetime import datetime, timezone
from typing import Any, Dict

SUPPORTED_TARGETS = ("braket", "originq", "spinq")


# ==================== 通用门分解（照抄 gate_identities.md） ====================
def _expand_ccx(match):
    """展开 ccx 为 15 个门的序列（速查表第5条）"""
    parts = [p.strip() for p in match.group(1).split(',')]
    if len(parts) != 3:
        return match.group(0)
    a, b, c = parts[0], parts[1], parts[2]
    return (f"h {c}; cx {b}, {c}; tdg {c}; cx {a}, {c}; t {c}; cx {b}, {c}; tdg {c}; "
            f"cx {a}, {c}; t {b}; t {c}; h {c}; cx {a}, {b}; t {a}; tdg {b}; cx {a}, {b};")

def _expand_swap(match):
    """展开 swap 为 3 个 cx（速查表第3条）"""
    parts = [p.strip() for p in match.group(1).split(',')]
    if len(parts) != 2:
        return match.group(0)
    a, b = parts[0], parts[1]
    return f"cx {a}, {b}; cx {b}, {a}; cx {a}, {b};"

def _apply_gate_decomposition(qasm: str) -> str:
    # 1. ccz → h target; ccx (ctrl1, ctrl2, target); h target;
    qasm = re.sub(r'ccz\s*\(?\s*([^,;]+)\s*,\s*([^,;]+)\s*,\s*([^,;]+)\s*\)?\s*;', 
                  lambda m: f"h {m.group(3).strip()}; ccx ({m.group(1).strip()}, {m.group(2).strip()}, {m.group(3).strip()}); h {m.group(3).strip()};", qasm)

    # 2. ccx → 15门序列
    qasm = re.sub(r'ccx\s*\(([^;]+)\);', _expand_ccx, qasm)

    # 3. swap → 3 cx
    qasm = re.sub(r'swap\s*\(?\s*([^,;]+)\s*,\s*([^,;]+)\s*\)?\s*;', 
                  lambda m: f"cx {m.group(1).strip()}, {m.group(2).strip()}; cx {m.group(2).strip()}, {m.group(1).strip()}; cx {m.group(1).strip()}, {m.group(2).strip()};", qasm)

    # 4. 相位门 → u1(θ)（注意顺序：先长后短，避免 tdg → t + dg 误匹配）
    qasm = re.sub(r'\btdg\s*([^;]+);', r'u1(-pi/4) \1;', qasm)
    qasm = re.sub(r'\bsdg\s*([^;]+);', r'u1(-pi/2) \1;', qasm)
    qasm = re.sub(r'\bt\s*([^;]+);', r'u1(pi/4) \1;', qasm)
    qasm = re.sub(r'\bs\s*([^;]+);', r'u1(pi/2) \1;', qasm)
    qasm = re.sub(r'\bz\s*([^;]+);', r'u1(pi) \1;', qasm)

    return qasm


def transpile(qasm_str: str, target: str) -> str:
    """Convert OpenQASM 2.0 to target's native format."""
    # ----- 第一步：通用门分解（所有后端都执行） -----
    qasm_str = _apply_gate_decomposition(qasm_str)

    # ----- 第二步：平台特定转换 -----
    if target == "braket":
        # Braket 要求 QASM 3.0 语法，并将 u1/cu1 转换为 phaseshift/cphaseshift
        qasm_str = re.sub(r'u1\(([^)]+)\)', r'phaseshift(\1)', qasm_str)
        qasm_str = re.sub(r'cu1\(([^)]+)\)', r'cphaseshift(\1)', qasm_str)

        # 转换 QASM 2.0 声明为 QASM 3.0
        lines = qasm_str.splitlines()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("include"):
                continue
            if stripped.startswith("OPENQASM 2.0"):
                new_lines.append("OPENQASM 3.0;")
                continue
            if "qreg" in stripped:
                m = re.search(r'qreg\s+(\w+)\[(\d+)\];', stripped)
                if m:
                    name, size = m.groups()
                    new_lines.append(f"qubit[{size}] {name};")
                    continue
            if "creg" in stripped:
                m = re.search(r'creg\s+(\w+)\[(\d+)\];', stripped)
                if m:
                    name, size = m.groups()
                    new_lines.append(f"bit[{size}] {name};")
                    continue
            if "measure" in stripped:
                m = re.match(r'^\s*measure\s+(\w+)\s*->\s*(\w+)\s*;', stripped)
                if m:
                    q, c = m.groups()
                    new_lines.append(f"{c} = measure {q};")
                    continue
                m = re.match(r'^\s*measure\s+(\w+)\s*;', stripped)
                if m:
                    q = m.group(1)
                    new_lines.append(f"c = measure {q};")
                    continue
            # cx → cnot (Braket 标准)
            line = re.sub(r'\bcx\b', 'cnot', line)
            new_lines.append(line)
        return "\n".join(new_lines)

    if target == "originq":
        # pyqpanda 原生支持 u1, cu1, cx, ry, rz，直接返回分解后的 QASM 2.0
        return qasm_str

    if target == "spinq":
        # SpinQ 也原生支持 u1, cu1 等，直接返回分解后的 QASM 2.0
        return qasm_str

    raise NotImplementedError(f"Transpile for target '{target}' not implemented")


def run(qasm_str: str, target: str, shots: int) -> Dict[str, Any]:
    """Execute circuit on target backend and return unified result."""
    # 先进行门分解（保证后端收到的都是基础门）
    qasm_str = _apply_gate_decomposition(qasm_str)

    if target == "braket":
        from braket.devices import LocalSimulator
        from braket.ir.openqasm import Program

        qasm3 = transpile(qasm_str, target)
        if not qasm3.strip():
            raise RuntimeError("Transpilation produced empty circuit")

        device = LocalSimulator(backend="braket_sv")
        program = Program(source=qasm3)
        task = device.run(program, shots=shots)
        result = task.result()

        counts = result.measurement_counts
        job_id = task.id
        timestamp = getattr(task.metadata, 'createdAt', None)
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        if counts:
            num_qubits = len(next(iter(counts.keys())))
        else:
            m = re.search(r'qubit\[(\d+)\]', qasm3)
            num_qubits = int(m.group(1)) if m else 2

        depth = 0
        for line in qasm3.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("OPENQASM", "qubit", "bit", "//")):
                depth += 1

        return {
            "backend": "aws_local_simulator",
            "job_id": job_id,
            "shots": shots,
            "counts": dict(counts),
            "bit_order": "little",
            "timestamp": timestamp,
            "meta": {"qubits_count": num_qubits, "depth": depth}
        }

    if target == "originq":
        try:
            import pyqpanda as pq
        except ImportError:
            raise RuntimeError("pyqpanda module not installed. Please install with: pip install pyqpanda")

        machine = pq.CPUQVM()
        machine.init_qvm()

        try:
            if hasattr(pq, 'convert_qasm_string_to_qprog'):
                prog, qreg, creg = pq.convert_qasm_string_to_qprog(qasm_str, machine)
            else:
                prog = pq.convert_qasm_to_qprog(qasm_str, machine)
                qreg = machine.get_allocate_qubits()
                creg = machine.get_allocate_cbits()
        except Exception as e:
            machine.finalize()
            raise RuntimeError(f"QASM conversion failed: {e}")

        raw_counts = machine.run_with_configuration(prog, creg, shots)
        machine.finalize()

        num_bits = len(creg)
        formatted_counts = {}
        for key, val in raw_counts.items():
            if isinstance(key, str) and set(key).issubset({'0', '1'}):
                bin_str = key.zfill(num_bits) if len(key) < num_bits else key[-num_bits:]
            elif isinstance(key, int):
                bin_str = format(key, f'0{num_bits}b')
            elif isinstance(key, str) and key.isdigit():
                bin_str = format(int(key), f'0{num_bits}b')
            else:
                bin_str = str(key)
            formatted_counts[bin_str] = val

        depth = 0
        for line in qasm_str.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(('OPENQASM', 'qreg', 'creg', 'include', '//', 'measure')):
                depth += 1

        return {
            "backend": "originq_cpu_simulator",
            "job_id": "originq-local-job",
            "shots": shots,
            "counts": formatted_counts,
            "bit_order": "little",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "meta": {"qubits_count": num_bits, "depth": depth}
        }

    if target == "spinq":
        from spinqit.compiler.qasm_compiler import QASMCompiler
        from spinqit import BasicSimulatorBackend, BasicSimulatorConfig
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', suffix='.qasm', delete=False) as f:
            f.write(qasm_str)
            path = f.name

        try:
            compiler = QASMCompiler()
            ir = compiler.compile(path, level=0)
            config = BasicSimulatorConfig()
            config.configure_shots(shots)
            backend = BasicSimulatorBackend()
            result = backend.execute(ir, config)
            raw_counts = result.counts
        finally:
            os.unlink(path)

        normalized_counts = raw_counts

        depth = 0
        for line in qasm_str.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(('OPENQASM', 'qreg', 'creg', 'include', '//')):
                depth += 1

        qubit_count = 0
        for line in qasm_str.splitlines():
            if 'qreg' in line:
                import re
                m = re.search(r'qreg\s+\w+\[(\d+)\]', line)
                if m:
                    qubit_count = int(m.group(1))
                    break

        return {
        "backend": "spinq_basic_simulator",
        "job_id": "spinq-local-job",
        "shots": shots,
        "counts": normalized_counts,
        "bit_order": "little",
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "meta": {"qubits_count": qubit_count, "depth": depth}
        }

    raise NotImplementedError(f"Run for target '{target}' not implemented")


SYSTEM_PROMPT = """
你是一个专业的量子电路生成助手。你要识别是下面三个任务中的哪一个：
任务一：根据用户的自然语言描述，生成对应的、语法正确的 OpenQASM 2.0 电路代码。

## 一、基础知识（快速复习）
- 量子比特（qubit）用 q 表示，经典比特（bit）用 c 表示。
- 电路是时间顺序的：门从左到右依次应用。
- 测量将量子比特状态映射为经典 0/1。

## 二、OpenQASM 2.0 语法规则（必须严格遵守）
1. 程序必须以 `OPENQASM 2.0;` 开头。
2. 第二行必须包含 `include "qelib1.inc";`（标准库定义常用门）。
3. 声明量子寄存器：`qreg 名称[数量];`，例如 `qreg q[3];`
4. 声明经典寄存器：`creg 名称[数量];`，例如 `creg c[3];`
5. 所有量子门和测量语句以分号 `;` 结尾。
6. 支持的门（不区分大小写，但必须使用小写名称）：
   - 单比特门：`h`, `x`, `s`, `sdg`, `t`, `tdg`, `ry(theta)`, `rz(theta)`
   - 两比特门：`cx`（CNOT，控制-目标）, `swap`, `cu1(lambda)`（受控相位）
   - 三比特门：`ccx`（Toffoli）
   - 测量：`measure 量子寄存器 -> 经典寄存器;` 或逐个测量 `measure q[i] -> c[i];`
7. 测量应放在所有门操作之后。
8. 寄存器大小必须足够容纳所操作的索引（例如有 `q[3]` 才能用 `q[2]`）。
9. 代码中不要包含任何注释（除了 QASM 注释 `//`）或额外解释文字。
10. 代码中只能用第6点列出的门，不能使用其他自定义门或库。

## 三、完整电路示例（请参考这些模板）

### 示例1：贝尔态（2 比特）
输入: "生成一个 2 比特贝尔态"
输出:
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0], q[1];
measure q -> c;

### 示例2：3 比特 GHZ 态
输入: "生成一个 3 比特 GHZ 态并全测量"
输出:
OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
creg c[3];
h q[0];
cx q[0], q[1];
cx q[1], q[2];
measure q -> c;

### 示例3：交换两个量子比特
输入: "交换 q[0] 和 q[2]"
输出:
OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
creg c[3];
swap q[0], q[2];
measure q -> c;

### 示例4：带旋转门的电路
输入: "对 q[0] 做 Rx(pi/2)，然后与 q[1] 做 CNOT"
输出:
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
rx(pi/2) q[0];
cx q[0], q[1];
measure q -> c;

### 示例5：5 比特 GHZ 态
输入: "生成 5 比特 GHZ 态"
输出:
OPENQASM 2.0;
include "qelib1.inc";
qreg q[5];
creg c[5];
h q[0];
cx q[0], q[1];
cx q[1], q[2];
cx q[2], q[3];
cx q[3], q[4];
measure q -> c;

## 四、输出格式要求（极其重要）
- 只输出纯 QASM 代码，**不要**包含任何解释、注释（除了 QASM 标准注释 `//`）或 Markdown 代码块（如 ```qasm）。
- 代码必须从 `OPENQASM 2.0;` 开始，到最后一个 `measure` 语句结束。
- 如果用户描述不够明确（如未指定比特数），请根据常见含义合理推断（例如 GHZ 通常为 3 比特，贝尔态为 2 比特），并在输出前不作任何说明。
- 如果用户要求包含特定门，请确保使用正确的语法（如 `ry(theta)` 中的 theta 用 `pi/2` 或 `3.14159` 表示）。
- 检查输出的结果，如果发现用了不支持的门或语法错误，请重新生成，确保完全符合 OpenQASM 2.0 规范。

现在，请根据用户的请求生成对应的 QASM 代码。

任务二：如果用户要求你修改量子电路，请在用户给的 QASM 代码中直接进行修改，确保输出仍然符合 OpenQASM 2.0 规范（参考任务一的规范），
输出格式为“以下为修改后的正确代码”+纯 QASM 代码 或者 “未找到可修改的代码” 或者 “代码正确”。

任务三：如果用户要求你推荐量子模拟器后端，输出“Hello”
"""
# ==================== L2 智能体 ====================
import json
import os

def _load_backend_data():
    """从 backend_capabilities.json 加载后端列表，返回 (列表, ID集合)"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend_capabilities.json")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        backends = data.get("backends", [])
        ids = {b["id"] for b in backends}
        return backends, ids
    except:
        return [], set()

_BACKENDS, _VALID_IDS = _load_backend_data()

def _build_system_prompt():
    """动态生成系统提示，包含后端能力表"""
    if _BACKENDS:
        summary = "\n".join(
            f"- {b['id']}: {b['kind']}, max_qubits={b['max_qubits']}, queue={b['queue']}, cost={b['cost']}"
            for b in _BACKENDS
        )
    else:
        summary = "（暂无后端数据，请按常识推荐）"

    return f"""你是一个量子计算助手。根据用户输入自行判断意图，并按格式输出：

- 若用户要生成或修正电路：输出纯 OpenQASM 2.0 代码（以 OPENQASM 2.0; 开头，含 qreg/creg/measure）。
- 若用户要推荐后端：根据以下能力表里的约束，{summary}，只允许输出以下内容之一：
1.一个合法后端ID，不加解释
2.超出已有的后端能力
3.对不起，不知道。

绝对不要包含 Markdown 代码块或额外文字。"""

def _extract_qasm(text: str) -> str:
    """从文本中提取 OpenQASM 2.0 代码块"""
    if not isinstance(text, str):
        return ""
    # 匹配从 OPENQASM 2.0 开始，直到遇见 ``` 或结尾
    match = re.search(r"(OPENQASM\s+2\.0;.*?)(?=\s*```|\Z)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 若没有，尝试找包含 qreg 和 creg 的段落
    match = re.search(r"(qreg\s+.*?;\s*creg\s+.*?;.*?measure.*?;)", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

def _extract_backend(text: str) -> str:
    """从文本中提取已知后端标识符（基于 _VALID_IDS）"""
    if not isinstance(text, str) or not _VALID_IDS:
        return ""
    import re
    for ident in _VALID_IDS:
        if re.search(re.escape(ident), text, re.IGNORECASE):
            return ident
    # 兜底：分词匹配
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    for w in words:
        if w.lower() in {v.lower() for v in _VALID_IDS}:
            return w
    return ""

def _verify_qasm(qasm: str) -> bool:
    """用 run 执行 QASM（braket 本地模拟器），验证是否能正常跑通"""
    try:
        result = run(qasm, "braket", 1024)
        if not isinstance(result, dict) or "counts" not in result:
            return False
        total = sum(result["counts"].values())
        return total == 1024
    except Exception:
        return False

def agent_chat(user_prompt: str) -> str:
    """L2 智能体入口：LLM 自主判断意图，动态提示包含后端能力表"""
    from llm_client import chat_completion

    system_prompt = _build_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    last_output = ""
    # 最多尝试 2 次（初次 + 1 次重试）
    for attempt in range(2):
        try:
            response = chat_completion(messages)
            output = response["choices"][0]["message"]["content"].strip()
            last_output = output
        except Exception as e:
            last_output = f"LLM error: {e}"
            break

        # 尝试提取 QASM 并验证
        qasm = _extract_qasm(output)
        if qasm and _verify_qasm(qasm):
            return qasm

        # 尝试提取后端标识
        backend = _extract_backend(output)
        if backend:
            return backend

        # 如果都无效，且还有重试机会，则反馈格式错误
        if attempt == 0:
            messages.append({"role": "assistant", "content": output})
            messages.append({
                "role": "user",
                "content": "输出格式不正确。请只输出纯 QASM 代码或有效的后端 ID，不要添加任何额外文字。"
            })

    # 最后一次尝试：尽量提取
    qasm = _extract_qasm(last_output)
    if qasm:
        return qasm
    backend = _extract_backend(last_output)
    if backend:
        return backend
    return last_output  # 实在无法提取则原样返回


# ==================== L3 占位 ====================
def compile_hybrid(hybrid_qasm_str: str) -> tuple:
    raise NotImplementedError("L3 not implemented")

# ==================== 交互入口（可选） ====================
if __name__ == "__main__":
    import sys
    print("LoomQ Agent 交互模式 (输入 'exit' 退出)")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input.strip():
            continue
        try:
            reply = agent_chat(user_input)
            print(reply)
            print("---")
        except Exception as e:
            print(f"错误: {e}")


