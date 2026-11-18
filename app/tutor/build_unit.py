#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build one authored unit, then run the verification gate.

This is the deterministic "one-click build" step. It does NOT author medical
content: content must already exist in tutor/content/{unit}_content.json and
the matching compile_{unit} function must exist in compile_units.py.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def available_units():
    import compile_units as cu
    return {
        name[len("compile_"):]: getattr(cu, name)
        for name in dir(cu)
        if name.startswith("compile_") and callable(getattr(cu, name))
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", default="asthma", help="unit id, e.g. asthma/pte/copd")
    parser.add_argument("--all", action="store_true", help="build all discovered compile_* functions")
    parser.add_argument("--no-gate", action="store_true", help="skip verify_unit.py")
    args = parser.parse_args()

    builders = available_units()
    targets = list(builders) if args.all else [args.unit]
    unknown = [u for u in targets if u not in builders]
    if unknown:
        print(f"[FAIL] 找不到编译函数 compile_*: {unknown}")
        print(f"可用 unit: {sorted(builders)}")
        return 1

    failed = []
    for unit in targets:
        print(f"\n=== build {unit} ===")
        started = time.time()
        try:
            builders[unit]()
        except Exception as e:
            print(f"[FAIL] {unit} 编译失败: {e}")
            failed.append(unit)
            continue
        print(f"[OK] {unit} 编译完成，用时 {time.time() - started:.2f}s")

        if not args.no_gate:
            gate_started = time.time()
            result = subprocess.run(
                [sys.executable, str(HERE / "verify_unit.py"), unit],
                cwd=str(HERE),
            )
            if result.returncode != 0:
                print(f"[FAIL] {unit} 门禁未通过")
                failed.append(unit)
                continue
            print(f"[OK] {unit} 门禁通过，用时 {time.time() - gate_started:.2f}s")

    if failed:
        print(f"\n[FAIL] 未通过: {failed}")
        return 1
    print("\n[OK] 构建与门禁全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
