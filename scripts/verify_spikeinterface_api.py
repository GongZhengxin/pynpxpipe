#!/usr/bin/env python3
"""Verify SpikeInterface API calls used in architecture.md.

Checks:
1. SpikeInterface version >= 0.104.0
2. All 9 API functions exist and are importable
3. Print docstrings for manual review
"""

import sys


def check_version():
    import spikeinterface as si
    version = si.__version__
    major, minor = map(int, version.split('.')[:2])
    print(f"SpikeInterface version: {version}")
    if major == 0 and minor < 104:
        print(f"[FAIL] ERROR: SpikeInterface {version} < 0.104.0")
        sys.exit(1)
    print("[PASS] Version check passed\n")


def verify_preprocessing_apis():
    print("=" * 60)
    print("PREPROCESSING APIs")
    print("=" * 60)
    try:
        from spikeinterface.preprocessing import (
            phase_shift,
            bandpass_filter,
            detect_bad_channels,
            common_reference,
            correct_motion,
        )
        for name, fn in [
            ("1. phase_shift", phase_shift),
            ("2. bandpass_filter", bandpass_filter),
            ("3. detect_bad_channels", detect_bad_channels),
            ("4. common_reference", common_reference),
            ("5. correct_motion", correct_motion),
        ]:
            print(f"\n{name}")
            print("-" * 40)
            doc = fn.__doc__
            print(doc[:800] if doc else "No docstring")
        print("\n[PASS] All preprocessing APIs importable\n")
    except ImportError as e:
        print(f"[FAIL] ERROR: {e}")
        sys.exit(1)


def verify_sorter_api():
    print("=" * 60)
    print("SORTERS API")
    print("=" * 60)
    try:
        from spikeinterface.sorters import run_sorter
        print("\n6. run_sorter")
        print("-" * 40)
        doc = run_sorter.__doc__
        print(doc[:800] if doc else "No docstring")
        print("\n[PASS] Sorters API importable\n")
    except ImportError as e:
        print(f"[FAIL] ERROR: {e}")
        sys.exit(1)


def verify_core_api():
    print("=" * 60)
    print("CORE API")
    print("=" * 60)
    try:
        from spikeinterface.core import create_sorting_analyzer
        print("\n7. create_sorting_analyzer")
        print("-" * 40)
        doc = create_sorting_analyzer.__doc__
        print(doc[:800] if doc else "No docstring")
        print("\n[PASS] Core API importable\n")
    except ImportError as e:
        print(f"[FAIL] ERROR: {e}")
        sys.exit(1)


def verify_curation_apis():
    print("=" * 60)
    print("CURATION APIs")
    print("=" * 60)
    try:
        from spikeinterface.curation import (
            bombcell_label_units,
            compute_merge_unit_groups,
        )
        for name, fn in [
            ("8. bombcell_label_units", bombcell_label_units),
            ("9. compute_merge_unit_groups", compute_merge_unit_groups),
        ]:
            print(f"\n{name}")
            print("-" * 40)
            doc = fn.__doc__
            print(doc[:800] if doc else "No docstring")
        print("\n[PASS] All curation APIs importable\n")
    except ImportError as e:
        print(f"[FAIL] ERROR: {e}")
        sys.exit(1)


def main():
    print("\n" + "=" * 60)
    print("SpikeInterface API Verification")
    print("=" * 60 + "\n")
    check_version()
    verify_preprocessing_apis()
    verify_sorter_api()
    verify_core_api()
    verify_curation_apis()
    print("=" * 60)
    print("[PASS] ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
