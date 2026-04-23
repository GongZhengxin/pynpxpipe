"""tools/verify_gpu.py — Standalone torch/CUDA consistency check.

Prints the live state of torch + CUDA and compares it against
``.venv/.gpu_stack_lock.json`` (written by ``install_sort_stack.py``).
Exits 0 on match, 1 on mismatch or missing wheel.

Safe to run at any time; does not modify the environment.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _venv_root() -> Path:
    env = os.environ.get("VIRTUAL_ENV")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / ".venv"


def _load_lock() -> dict | None:
    path = _venv_root() / ".gpu_stack_lock.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    print("pynpxpipe GPU stack verification")
    print("-" * 40)

    lock = _load_lock()
    if lock is None:
        print("  Lock file : (not found — run `tools/install_sort_stack.py` first)")
    else:
        print(f"  Lock file : {lock}")

    try:
        import torch
    except ImportError:
        print("  torch     : NOT INSTALLED")
        return 1

    cuda_ok = bool(torch.cuda.is_available())
    print(f"  torch     : {torch.__version__}")
    print(f"  cuda ok   : {cuda_ok}")
    if cuda_ok:
        try:
            print(f"  device    : {torch.cuda.get_device_name(0)}")
            cap = torch.cuda.get_device_capability(0)
            print(f"  compute   : sm_{cap[0]}{cap[1]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  (device probe failed: {exc})")

    if lock is None:
        return 1

    expected = lock.get("wheel_tag")
    if expected and expected != "cpu" and not cuda_ok:
        print(
            f"\n  MISMATCH: lock says {expected} but torch.cuda.is_available()=False. "
            "Re-run `tools/install_sort_stack.py --force`."
        )
        return 1
    if expected == "cpu" and cuda_ok:
        print(
            "\n  NOTE: lock says cpu but CUDA is live. Either update the lock "
            "(`install_sort_stack.py --force`) or ignore if intentional."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
