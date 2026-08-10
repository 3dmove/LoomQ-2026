#!/usr/bin/env python3
"""
本源量子 pyqpanda 平台接入最小可跑示例
演示如何导入 OpenQASM 2.0 字符串，转译为本源量子程序，并运行在 CPU 模拟器上。
"""

import json

try:
    import pyqpanda as pq
except ImportError:
    pq = None


def run_on_originq_simulator(qasm_str: str, shots: int = 1024) -> dict:
    if pq is None:
        print("[Warning] 未检测到 pyqpanda 模块，将返回 Mock 数据。")
        return {
            "backend": "originq_cpu_simulator_mock",
            "job_id": "mock-job-123",
            "shots": shots,
            "counts": {"00": 510, "11": 514},
            "bit_order": "little",
            "timestamp": "2026-07-06T10:00:00Z",
            "meta": {"info": "Mock data since pyqpanda is not installed"}
        }

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
        raise RuntimeError(f"QASM 转译失败: {e}")

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
        "job_id": "originq-sim-job-local",
        "shots": shots,
        "counts": formatted_counts,
        "bit_order": "little",
        "timestamp": "2026-07-06T10:00:00Z",  # 可改为动态
        "meta": {
            "qubits_count": num_bits,
            "depth": depth
        }
    }


def main():
    qasm_str = """
    OPENQASM 2.0;
    include "qelib1.inc";
    qreg q[2];
    creg c[2];
    h q[0];
    cx q[0],q[1];
    measure q[0] -> c[0];
    measure q[1] -> c[1];
    """
    print("--- 待转译的 QASM 2.0 电路 ---")
    print(qasm_str.strip())
    print("----------------------------")

    res = run_on_originq_simulator(qasm_str, shots=1024)
    print("\n运行并标准化后的统一输出结果:")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()