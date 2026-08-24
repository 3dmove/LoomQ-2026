#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LoomQ adapter supporting Braket (braket), OriginQ (originq), and SpinQ (spinq)."""
import re
from datetime import datetime, timezone
from typing import Any, Dict

SUPPORTED_TARGETS = ("braket", "originq", "spinq")


# ==================== 辅助函数：移除 measure（量旋云专用） ====================
def remove_measure_statements(qasm: str) -> str:
    """移除 QASM 代码中的所有 measure 语句（量旋云平台不需要）"""
    lines = qasm.splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # 跳过包含 measure 的行（无论空格、箭头格式如何）
        if re.search(r'\bmeasure\b', stripped, re.IGNORECASE):
            continue
        new_lines.append(line)
    return "\n".join(new_lines)


# ==================== 可视化辅助函数 ====================
def draw_circuit_ascii(qasm_str: str) -> str:
    """使用 Qiskit 生成 ASCII 电路图"""
    try:
        from qiskit import QuantumCircuit
        qc = QuantumCircuit.from_qasm_str(qasm_str)
        return qc.draw(output='text')
    except Exception:
        return "（电路图生成失败，请确保已安装 qiskit）"


def plot_counts_bar(counts: dict, title: str = "测量结果分布") -> None:
    """使用 matplotlib 绘制柱状图并显示"""
    if not counts:
        print("无数据可绘图")
        return
    try:
        import matplotlib.pyplot as plt
        labels = list(counts.keys())
        values = list(counts.values())
        plt.figure(figsize=(8, 5))
        plt.bar(labels, values, color='skyblue')
        plt.xlabel("量子态")
        plt.ylabel("计数")
        plt.title(title)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()
    except ImportError:
        print("⚠️ matplotlib 未安装，无法显示柱状图。")
    except Exception as e:
        print(f"⚠️ 柱状图显示失败: {e}")


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

    # ==================== SpinQ 分支（含云后端支持） ====================
    if target == "spinq":
        qasm_str = remove_measure_statements(qasm_str)   # 量旋云不需要 measure
        import os
        import tempfile
        from spinqit.compiler.qasm_compiler import QASMCompiler
        from spinqit import BasicSimulatorBackend, BasicSimulatorConfig

        with tempfile.NamedTemporaryFile(mode='w', suffix='.qasm', delete=False) as f:
            f.write(qasm_str)
            path = f.name
        try:
            compiler = QASMCompiler()
            ir = compiler.compile(path, level=0)
            config = BasicSimulatorConfig()
            config.configure_shots(shots)

            use_cloud = os.environ.get("SPINQ_USE_CLOUD", "false").lower() == "true"
            if use_cloud:
                from spinqit import get_spinq_cloud
                username = os.environ.get("SPINQ_CLOUD_USERNAME")
                keyfile = os.environ.get("SPINQ_CLOUD_KEYFILE", "~/.ssh/id_rsa")
                if not username:
                    raise RuntimeError("SPINQ_CLOUD_USERNAME must be set when using cloud backend")
                backend = get_spinq_cloud(username=username, keyfile=keyfile)
                config.metadata['platform'] = os.environ.get("SPINQ_PLATFORM", "Taurus")
                result = backend.execute(ir, config)
                job_id = getattr(result, 'job_id', 'spinq-cloud-job')
                backend_name = "spinq_cloud"
            else:
                backend = BasicSimulatorBackend()
                result = backend.execute(ir, config)
                job_id = "spinq-local-job"
                backend_name = "spinq_basic_simulator"

            raw_counts = result.counts
        finally:
            os.unlink(path)

        # 归一化位序
        normalized_counts = {}
        for key, val in raw_counts.items():
            normalized_counts[key[::-1]] = val

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
            "backend": backend_name,
            "job_id": job_id,
            "shots": shots,
            "counts": normalized_counts,
            "bit_order": "little",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "meta": {"qubits_count": qubit_count, "depth": depth}
        }

    raise NotImplementedError(f"Run for target '{target}' not implemented")


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
    match = re.search(r"(OPENQASM\s+2\.0;.*?)(?=\s*```|\Z)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"(qreg\s+.*?;\s*creg\s+.*?;.*?measure.*?;)", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

def _extract_backend(text: str) -> str:
    """从文本中提取已知后端标识符"""
    if not isinstance(text, str) or not _VALID_IDS:
        return ""
    for ident in _VALID_IDS:
        if re.search(re.escape(ident), text, re.IGNORECASE):
            return ident
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    for w in words:
        if w.lower() in {v.lower() for v in _VALID_IDS}:
            return w
    return ""

def _verify_qasm(qasm: str) -> bool:
    """用 run 执行 QASM（braket 本地模拟器）验证是否能跑通"""
    try:
        result = run(qasm, "braket", 1024)
        if not isinstance(result, dict) or "counts" not in result:
            return False
        total = sum(result["counts"].values())
        return total == 1024
    except Exception:
        return False

def agent_chat(user_prompt: str) -> str:
    """L2 智能体入口"""
    try:
        from .llm_client import chat_completion
    except ImportError:
        from llm_client import chat_completion

    system_prompt = _build_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    last_output = ""
    for attempt in range(2):
        try:
            response = chat_completion(messages)
            output = response["choices"][0]["message"]["content"].strip()
            last_output = output
        except Exception as e:
            last_output = f"LLM error: {e}"
            break

        qasm = _extract_qasm(output)
        if qasm and _verify_qasm(qasm):
            return qasm

        backend = _extract_backend(output)
        if backend:
            return backend

        if attempt == 0:
            messages.append({"role": "assistant", "content": output})
            messages.append({
                "role": "user",
                "content": "输出格式不正确。请只输出纯 QASM 代码或有效的后端 ID，不要添加任何额外文字。"
            })

    qasm = _extract_qasm(last_output)
    if qasm:
        return qasm
    backend = _extract_backend(last_output)
    if backend:
        return backend
    return last_output


# ==================== L3 占位 ====================
def compile_hybrid(hybrid_qasm_str: str) -> tuple:
    raise NotImplementedError("L3 not implemented")


# ==================== 交互入口（含小白指引和可视化） ====================
if __name__ == "__main__":
    import sys

    print("\n" + "="*60)
    print("🌟 欢迎使用 LoomQ 量子计算助手！")
    print("="*60)
    print("量子计算利用量子比特（qubit）的叠加态和纠缠态进行计算。")
    print("你可以用自然语言描述你想要实现的量子电路，我会帮你生成代码并运行。")
    print("\n📌 试试输入以下示例：")
    print("  - 生成一个 2 比特贝尔态")
    print("  - 修改以下量子电路：OPENQASM 2.0; qreg q[2]; creg c[2]; h q[0]; cx q[0], q[1];")
    print("  - 推荐一个 20 比特后端")
    print("  - 运行刚才生成的电路（我会提示你）")
    print("\n💡 输入 'exit' 退出，输入 'help' 查看帮助。")
    print("="*60)

    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break

        if user_input.lower() in ("exit", "quit"):
            print("👋 再见！")
            break

        if user_input.lower() == "help":
            print("\n可用的命令示例：")
            print("  - 生成一个 2 比特贝尔态")
            print("  - 修改以下量子电路：OPENQASM 2.0; qreg q[2]; creg c[2]; h q[0]; cx q[0], q[1];")
            print("  - 推荐一个 20 比特后端")
            continue

        if not user_input.strip():
            continue

        try:
            reply = agent_chat(user_input)
            print(reply)

            if "OPENQASM" in reply:
                print("\n🔍 检测到量子电路代码。")
                run_choice = input("是否在本地模拟器上运行此电路？(y/n): ").strip().lower()
                if run_choice == 'y':
                    qasm_extract = _extract_qasm(reply)
                    if not qasm_extract:
                        print("❌ 无法从回复中提取 QASM 代码，请检查格式。")
                    else:
                        print("⏳ 正在运行模拟...")
                        try:
                            result = run(qasm_extract, "braket", 1024)
                            counts = result.get("counts", {})
                            if counts:
                                print("✅ 运行成功！测量结果如下：")
                                total = sum(counts.values())
                                for state, cnt in sorted(counts.items()):
                                    prob = cnt / total * 100
                                    bar = "█" * int(prob / 2)
                                    print(f"  {state}: {cnt} ({prob:.1f}%) {bar}")
                                print("\n📐 电路图：")
                                print(draw_circuit_ascii(qasm_extract))
                                try:
                                    plot_counts_bar(counts, "测量结果分布")
                                except Exception as e:
                                    print(f"⚠️ 柱状图显示失败: {e}")
                            else:
                                print("⚠️ 运行结果为空。")
                        except Exception as e:
                            print(f"❌ 运行失败: {e}")
                else:
                    print("⏩ 跳过运行。")

            print("---")

        except Exception as e:
            print(f"❌ 错误: {e}")
            print("💡 如果输入格式有误，请尝试用更清晰的自然语言描述，或输入 'help' 查看示例。")
