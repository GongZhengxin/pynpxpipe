"""tools/install_sort_stack.py — one-shot installer for torch + kilosort.

pynpxpipe deliberately keeps **torch** and **kilosort** OUT of
``pyproject.toml`` so that ``uv sync`` never reverts a CUDA build to the
pypi CPU wheel. Run this script once after cloning / after your first
``uv sync`` to install a CUDA-matched torch and kilosort. Subsequent
``uv sync`` calls will not touch either package.

Usage
-----
    uv run python tools/install_sort_stack.py             # interactive
    uv run python tools/install_sort_stack.py --yes       # accept recommendation
    uv run python tools/install_sort_stack.py --cpu       # force CPU torch
    uv run python tools/install_sort_stack.py --cuda cu128  # force a wheel

Idempotency
-----------
After a successful install the script writes ``.venv/.gpu_stack_lock.json``
capturing the wheel tag, torch version, and NVIDIA driver version. On
re-run it compares the lock file to the live venv and exits early if
nothing has changed. Pass ``--force`` to reinstall regardless.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "pyyaml is required to read tools/cuda_matrix.yaml. "
        "Run `uv sync` first so that the core deps (incl. pyyaml) are installed.\n"
    )
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_PATH = REPO_ROOT / "tools" / "cuda_matrix.yaml"
WHEEL_BASE_URL = "https://download.pytorch.org/whl"


@dataclass
class DetectedGPU:
    name: str
    driver_version: str  # e.g. "580.88"
    compute_cap: str | None  # e.g. "12.0"; None if nvidia-smi didn't report


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> str:
    """Run a command, return stdout, swallow any encoding issues."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return result.stdout


def detect_gpu() -> DetectedGPU | None:
    """Query nvidia-smi for the primary GPU. Return None if unavailable."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,compute_cap",
                "--format=csv,noheader",
            ]
        )
    except RuntimeError:
        # Some older drivers lack compute_cap; retry without it.
        try:
            out = _run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version",
                    "--format=csv,noheader",
                ]
            )
        except RuntimeError:
            return None
        fields = [f.strip() for f in out.strip().splitlines()[0].split(",")]
        return DetectedGPU(name=fields[0], driver_version=fields[1], compute_cap=None)

    first = out.strip().splitlines()[0]
    fields = [f.strip() for f in first.split(",")]
    return DetectedGPU(
        name=fields[0],
        driver_version=fields[1],
        compute_cap=fields[2] if len(fields) > 2 else None,
    )


def _driver_major(version: str) -> int:
    """Extract the leading integer from a driver version like '580.88'."""
    m = re.match(r"(\d+)", version)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Matrix resolution
# ---------------------------------------------------------------------------


def load_matrix() -> dict:
    with MATRIX_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def recommend_wheel(gpu: DetectedGPU | None, matrix: dict) -> str:
    """Pick the best wheel tag for this GPU + driver combination."""
    wheels = matrix["available_wheels"]
    if gpu is None:
        return "cpu"

    driver_major = _driver_major(gpu.driver_version)

    # Compute-capability floor — hardware that requires a specific minimum tag.
    floor_tag: str | None = None
    if gpu.compute_cap:
        floor_map = matrix.get("compute_cap_floor", {})
        floor_tag = floor_map.get(gpu.compute_cap)

    # Rank wheels by listed order (newest → oldest). Pick the first one whose
    # min_driver is satisfied AND which is >= the compute-cap floor.
    wheel_order = [w["tag"] for w in wheels]

    def tag_rank(tag: str) -> int:
        return wheel_order.index(tag)

    floor_rank = tag_rank(floor_tag) if floor_tag in wheel_order else len(wheel_order) - 1

    for idx, wheel in enumerate(wheels):
        if wheel["tag"] == "cpu":
            continue
        if idx > floor_rank:
            # This wheel is older than the compute-cap floor — skip.
            continue
        if driver_major >= wheel["min_driver"]:
            return wheel["tag"]

    return "cpu"


def wheel_info(tag: str, matrix: dict) -> dict:
    for w in matrix["available_wheels"]:
        if w["tag"] == tag:
            return w
    raise ValueError(f"Unknown wheel tag: {tag!r}")


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------


def _prompt(msg: str, default: str = "") -> str:
    try:
        answer = input(msg).strip()
    except EOFError:
        answer = ""
    return answer or default


def interactive_select(recommended: str, matrix: dict, gpu: DetectedGPU | None) -> str:
    """Show the menu and let the user pick a wheel tag."""
    print()
    print("[2/5] Confirm torch build:")
    wheels = matrix["available_wheels"]
    for i, w in enumerate(wheels, 1):
        marker = "  ← default" if w["tag"] == recommended else ""
        cuda = f"CUDA {w['cuda_runtime']}" if w["cuda_runtime"] else "no GPU acceleration"
        print(f"  [{i}] {w['tag']:6} — {cuda}{marker}")
    print(f"  [{len(wheels) + 1}] custom — enter your own --index-url")
    print()

    raw = _prompt(f"  Select [1-{len(wheels) + 1}, Enter={recommended}]: ", default="")
    if not raw:
        return recommended
    try:
        idx = int(raw)
    except ValueError:
        print(f"  Invalid selection {raw!r}; using {recommended}.")
        return recommended
    if 1 <= idx <= len(wheels):
        return wheels[idx - 1]["tag"]
    if idx == len(wheels) + 1:
        tag = _prompt("  Custom wheel tag (e.g. cu118): ")
        return tag or recommended
    print(f"  Out-of-range selection {idx}; using {recommended}.")
    return recommended


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def _uv_cmd() -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError(
            "uv not found on PATH. Install it from https://docs.astral.sh/uv/ and retry."
        )
    return [uv, "pip", "install"]


def _pkg_base_name(spec: str) -> str:
    """Strip version/extras from a pip spec, e.g. 'kilosort>=4.0' -> 'kilosort'."""
    return re.split(r"[<>=!~\[\s]", spec, maxsplit=1)[0].strip()


def install_torch(tag: str, force: bool = False) -> None:
    # When force=True, pass --reinstall-package so uv actually replaces an
    # already-installed torch (e.g. a stale CPU wheel) instead of no-op'ing.
    # Plain `uv pip install torch --index-url ...` is idempotent: if torch is
    # already present, uv accepts whatever variant is there and skips the
    # download, which is exactly the bug that left users stuck on +cpu.
    cmd = _uv_cmd() + ["torch"]
    if tag != "cpu":
        cmd += ["--index-url", f"{WHEEL_BASE_URL}/{tag}"]
    if force:
        cmd += ["--reinstall-package", "torch"]
    print(f"\n  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def install_companions(matrix: dict, force: bool = False) -> None:
    for pkg in matrix.get("companion_packages", []):
        cmd = _uv_cmd() + [pkg["name"]]
        if pkg.get("no_deps"):
            cmd.append("--no-deps")
        if force:
            cmd += ["--reinstall-package", _pkg_base_name(pkg["name"])]
        print(f"\n  $ {' '.join(cmd)}")
        subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Verification + lock file
# ---------------------------------------------------------------------------


def venv_root() -> Path:
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        return Path(venv)
    return REPO_ROOT / ".venv"


def lock_file_path() -> Path:
    return venv_root() / ".gpu_stack_lock.json"


def verify_and_lock(tag: str, gpu: DetectedGPU | None) -> None:
    """Import torch, print diagnostic info, write lock file."""
    import importlib

    torch = importlib.import_module("torch")
    torch_version = torch.__version__
    cuda_ok = bool(torch.cuda.is_available())

    print("\n[5/5] Verification:")
    print(f"  torch.__version__                = {torch_version}")
    print(f"  torch.cuda.is_available()        = {cuda_ok}")
    if cuda_ok:
        try:
            dev_name = torch.cuda.get_device_name(0)
            cap = torch.cuda.get_device_capability(0)
            print(f"  torch.cuda.get_device_name(0)    = {dev_name}")
            print(f"  torch.cuda.get_device_capability = sm_{cap[0]}{cap[1]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  (device probe failed: {exc})")

    if tag != "cpu" and not cuda_ok:
        print(
            "  WARNING: CUDA wheel requested but torch.cuda.is_available()=False. "
            "Check that the installed wheel matches your driver."
        )

    lock = {
        "wheel_tag": tag,
        "torch_version": torch_version,
        "cuda_available": cuda_ok,
        "gpu_name": gpu.name if gpu else None,
        "driver_version": gpu.driver_version if gpu else None,
    }
    path = lock_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    print(f"  Lock file: {path}")


def load_lock() -> dict | None:
    path = lock_file_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install torch + kilosort matched to this machine's CUDA.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Accept the recommended wheel without prompting."
    )
    parser.add_argument(
        "--cuda", metavar="TAG", help="Force a wheel tag (e.g. cu128). Bypasses interaction."
    )
    parser.add_argument(
        "--cpu", action="store_true", help="Install CPU torch. Shortcut for --cuda cpu."
    )
    parser.add_argument(
        "--force", action="store_true", help="Reinstall even if lock file is already consistent."
    )
    parser.add_argument(
        "--skip-kilosort", action="store_true", help="Install torch only; skip kilosort."
    )
    args = parser.parse_args()

    if args.cpu and args.cuda:
        parser.error("--cpu and --cuda are mutually exclusive")

    matrix = load_matrix()

    print("[1/5] Detecting environment...")
    print(f"  Platform     : {sys.platform}")
    print(f"  Python       : {sys.version.split()[0]} ({sys.executable})")
    gpu = detect_gpu()
    if gpu:
        print(f"  GPU          : {gpu.name}")
        print(f"  NVIDIA driver: {gpu.driver_version}")
        if gpu.compute_cap:
            print(f"  Compute cap  : sm_{gpu.compute_cap.replace('.', '')}")
    else:
        print("  GPU          : none detected (nvidia-smi missing or no CUDA GPU)")

    recommended = recommend_wheel(gpu, matrix)
    print(f"  Recommended  : {recommended}")

    # Determine the chosen tag.
    if args.cpu:
        tag = "cpu"
    elif args.cuda:
        tag = args.cuda
    elif args.yes:
        tag = recommended
    else:
        tag = interactive_select(recommended, matrix, gpu)

    # Idempotency: skip when the lock matches AND the live torch actually
    # matches the lock. A lock that records wheel_tag='cu128' but live torch
    # is '+cpu' means a previous install (or a strict `uv sync`) corrupted
    # the env — in that case we must reinstall even without --force.
    lock = load_lock()
    if lock and lock.get("wheel_tag") == tag and not args.force:
        try:
            import importlib

            torch = importlib.import_module("torch")
            live_version = torch.__version__
            live_cuda_ok = bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            live_version = ""
            live_cuda_ok = False
        recorded_version = lock.get("torch_version", "")
        expect_cuda = tag != "cpu"
        if live_version != recorded_version or live_cuda_ok != expect_cuda:
            print(
                f"\n  .gpu_stack_lock.json says wheel_tag={tag!r} (torch={recorded_version!r}, "
                f"cuda={lock.get('cuda_available')}) but live torch={live_version!r}, "
                f"cuda={live_cuda_ok}. Forcing reinstall to heal the drift."
            )
            args.force = True  # route through the --reinstall-package path below
        else:
            print(
                f"\n  .gpu_stack_lock.json already records wheel_tag={tag!r}; nothing to do. "
                "Pass --force to reinstall."
            )
            return 0

    print("\n[3/5] Planned actions:")
    reinstall_suffix = " --reinstall-package torch" if args.force else ""
    if tag == "cpu":
        print(f"  - uv pip install torch{reinstall_suffix}    (from pypi; CPU wheel)")
    else:
        print(
            f"  - uv pip install torch --index-url {WHEEL_BASE_URL}/{tag}"
            f"{reinstall_suffix}"
        )
    if not args.skip_kilosort:
        for pkg in matrix.get("companion_packages", []):
            flag = " --no-deps" if pkg.get("no_deps") else ""
            reflag = f" --reinstall-package {_pkg_base_name(pkg['name'])}" if args.force else ""
            print(f"  - uv pip install {pkg['name']}{flag}{reflag}")
    print(f"  - Write {lock_file_path()}")

    if not args.yes and not args.cpu and not args.cuda:
        proceed = _prompt("\n  Proceed? [Y/n]: ", default="y").lower()
        if proceed not in {"y", "yes", ""}:
            print("  Aborted.")
            return 1

    print("\n[4/5] Installing...")
    install_torch(tag, force=args.force)
    if not args.skip_kilosort:
        install_companions(matrix, force=args.force)

    verify_and_lock(tag, gpu)
    print("\nDone. Run `uv run python tools/verify_gpu.py` to re-check later.")
    print()
    print("IMPORTANT: From now on, use `uv sync --inexact ...` instead of `uv sync ...`.")
    print("  Plain `uv sync` operates in STRICT mode and will uninstall torch/kilosort")
    print("  (they are not in uv.lock — that's the whole point of this script).")
    print("  `--inexact` tells uv to leave out-of-lock packages alone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
