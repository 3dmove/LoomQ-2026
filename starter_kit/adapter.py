#!/usr/bin/env python3
"""LoomQ adapter supporting Braket (braket) and OriginQ (originq)."""
import re
from datetime import datetime, timezone
from typing import Any, Dict

SUPPORTED_TARGETS = ("braket", "originq")


def transpile(qasm_str: str, target: str) -> str:
    """Convert OpenQASM 2.0 to target's native format if needed."""
    if target == "braket":
        # Braket needs QASM 3.0; convert 2.0 syntax
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
            # Convert measure q -> c; to c = measure q;
            if "measure" in stripped:
                m = re.match(r'^\s*measure\s+(\w+)\s*->\s*(\w+)\s*;', stripped)
                if m:
                    q, c = m.groups()
                    new_lines.append(f"{c} = measure {q};")
                    continue
                m = re.match(r'^\s*measure\s+(\w+)\s*;', stripped)
                if m:
                    q = m.group(1)
                    # Use 'c' as default creg if not defined, but better to keep original
                    new_lines.append(f"c = measure {q};")
                    continue
            # Replace cx with cnot
            line = re.sub(r'\bcx\b', 'cnot', line)
            new_lines.append(line)
        return "\n".join(new_lines)

    if target == "originq":
        # pyqpanda accepts QASM 2.0 directly, no conversion needed
        return qasm_str

    raise NotImplementedError(f"Transpile for target '{target}' not implemented")


def run(qasm_str: str, target: str, shots: int) -> Dict[str, Any]:
    """Execute circuit on target backend and return unified result."""
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

        # Determine qubit count from counts keys
        if counts:
            num_qubits = len(next(iter(counts.keys())))
        else:
            m = re.search(r'qubit\[(\d+)\]', qasm3)
            num_qubits = int(m.group(1)) if m else 2

        # Estimate depth (non-declaration, non-comment lines)
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
            # Try new API first
            if hasattr(pq, 'convert_qasm_string_to_qprog'):
                prog, qreg, creg = pq.convert_qasm_string_to_qprog(qasm_str, machine)
            else:
                prog = pq.convert_qasm_to_qprog(qasm_str, machine)
                qreg = machine.get_allocate_qubits()
                creg = machine.get_allocate_cbits()
        except Exception as e:
            machine.finalize()
            raise RuntimeError(f"QASM conversion failed: {e}")

        # Execute
        raw_counts = machine.run_with_configuration(prog, creg, shots)
        machine.finalize()

        num_bits = len(creg)
        # Format counts: ensure binary string keys with correct length
        formatted_counts = {}
        for key, val in raw_counts.items():
            if isinstance(key, str) and set(key).issubset({'0', '1'}):
                # Already binary string, pad/truncate to num_bits
                bin_str = key.zfill(num_bits) if len(key) < num_bits else key[-num_bits:]
            elif isinstance(key, int):
                bin_str = format(key, f'0{num_bits}b')
            elif isinstance(key, str) and key.isdigit():
                bin_str = format(int(key), f'0{num_bits}b')
            else:
                bin_str = str(key)
            formatted_counts[bin_str] = val

        # Depth estimation
        depth = 0
        for line in qasm_str.splitlines():
            stripped = line.strip()
            if (stripped and not stripped.startswith(('OPENQASM', 'qreg', 'creg', 'include', '//', 'measure'))):
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

    raise NotImplementedError(f"Run for target '{target}' not implemented")


def agent_chat(prompt: str) -> str:
    raise NotImplementedError("L2 not implemented")


def compile_hybrid(hybrid_qasm_str: str) -> tuple:
    raise NotImplementedError("L3 not implemented")