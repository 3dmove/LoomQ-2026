#!/usr/bin/env python3
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
    """对 QASM 字符串应用所有门分解（降级为 h, cx, u1, rz, ry, measure）"""
    # 1. ccx → 15门序列
    qasm = re.sub(r'ccx\s*\(([^;]+)\);', _expand_ccx, qasm)
    # 2. swap → 3 cx
    qasm = re.sub(r'swap\s*\(([^;]+)\);', _expand_swap, qasm)
    # 3. 相位门家族 → u1(θ)
    qasm = re.sub(r'z\s*\(([^;]+)\);', r'u1(pi) \1;', qasm)
    qasm = re.sub(r's\s*\(([^;]+)\);', r'u1(pi/2) \1;', qasm)
    qasm = re.sub(r'sdg\s*\(([^;]+)\);', r'u1(-pi/2) \1;', qasm)
    qasm = re.sub(r't\s*\(([^;]+)\);', r'u1(pi/4) \1;', qasm)
    qasm = re.sub(r'tdg\s*\(([^;]+)\);', r'u1(-pi/4) \1;', qasm)
    # 注：rz, ry, h, x, cx, cu1 保持不变，它们被所有后端支持（或后续转换）
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
        from spinqit import QuantumCircuit, TaurusLocalSimulator

        qc = QuantumCircuit.from_qasm(qasm_str)
        sim = TaurusLocalSimulator()
        result = sim.run(qc, shots=shots)
        raw_counts = result.get_counts()

        # 位序归一化：SpinQ 返回的 key 是 big-endian（c[0]在左），需要反转成 little（c[0]在右）
        normalized_counts = {}
        for key, val in raw_counts.items():
            normalized_counts[key[::-1]] = val

        depth = 0
        for line in qasm_str.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(('OPENQASM', 'qreg', 'creg', 'include', '//')):
                depth += 1

        return {
            "backend": "spinq_taurus_simulator",
            "job_id": "spinq-local-job",
            "shots": shots,
            "counts": normalized_counts,
            "bit_order": "little",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "meta": {"qubits_count": qc.qubit_count, "depth": depth}
        }

    raise NotImplementedError(f"Run for target '{target}' not implemented")


def agent_chat(prompt: str) -> str:
    raise NotImplementedError("L2 not implemented")


def compile_hybrid(hybrid_qasm_str: str) -> tuple:
    raise NotImplementedError("L3 not implemented")