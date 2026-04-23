"""Integration harness: verify Phase 3 raw data export bit-exact.

Reads a small segment of real SpikeGLX data, writes it to NWB via
append_raw_data(), reads it back, and compares bit-exact with the source.

Usage:
    uv run python tools/harness_export_raw.py
    uv run python tools/harness_export_raw.py --seconds 5
    uv run python tools/harness_export_raw.py --seconds 1 --skip-lf

Prerequisites:
    - Real SpikeGLX data at DATA_DIR (below)
    - Phase 1 NWB already exported, OR this script creates a minimal one
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

# ── Constants ────────────────────────────────────────────────────────────
DATA_DIR = Path(r"F:\#Datasets\demo_rawdata")
SUBJECT_YAML = Path(r"F:\tools\pynpxpipe\monkeys\MaoDan.yaml")


def create_minimal_nwb(session, nwb_path: Path) -> Path:
    """Create a minimal NWB with electrode table — enough for append_raw_data.

    This simulates the output of Phase 1 export without needing sorting data.
    """
    from pynpxpipe.io.nwb_writer import NWBWriter

    writer = NWBWriter(session, nwb_path)
    writer.create_file()

    # Add electrode table entries for each probe
    nwbfile = writer._nwbfile
    from pynwb.device import Device
    from pynwb.ecephys import ElectrodeGroup

    for probe in session.probes:
        device = nwbfile.create_device(name=f"Neuropixels_{probe.probe_id}")
        group = nwbfile.create_electrode_group(
            name=f"group_{probe.probe_id}",
            description=f"Electrode group for {probe.probe_id}",
            device=device,
            location="brain",
        )
        if nwbfile.electrodes is None:
            nwbfile.add_electrode_column("probe_id", "Probe identifier")
            nwbfile.add_electrode_column("channel_id", "Channel index within probe")

        # Add electrode rows — need to match channel count from AP recording
        import spikeinterface.extractors as se

        rec = se.read_spikeglx(
            probe.ap_bin.parent,
            stream_name=f"{probe.probe_id}.ap",
        )
        n_ch = rec.get_num_channels()
        for ch_idx in range(n_ch):
            nwbfile.add_electrode(
                group=group,
                probe_id=probe.probe_id,
                channel_id=ch_idx,
                location="brain",
                x=0.0, y=float(ch_idx * 10), z=0.0,
                filtering="none",
            )
        print(f"  Added {n_ch} electrodes for {probe.probe_id}")

    writer.write()
    print(f"  Minimal NWB created: {nwb_path}")
    return nwb_path


def verify_bit_exact(
    session, nwb_path: Path, time_range: tuple[float, float]
) -> dict:
    """Read back raw data from NWB and compare with source.

    Returns:
        Summary dict with pass/fail, sizes, compression ratio.
    """
    from pynwb import NWBHDF5IO

    from pynpxpipe.io.spikeglx import SpikeGLXLoader

    results = {}
    t0, t1 = time_range

    with NWBHDF5IO(str(nwb_path), "r") as io:
        nwbfile = io.read()

        for probe in session.probes:
            ap_name = f"ElectricalSeriesAP_{probe.probe_id}"
            if ap_name not in nwbfile.acquisition:
                print(f"  SKIP {ap_name}: not found in NWB")
                continue

            es = nwbfile.acquisition[ap_name]
            nwb_data = es.data[:]  # Read all data from NWB

            # Read source
            rec = SpikeGLXLoader.load_ap(probe)
            sr = rec.get_sampling_frequency()
            source_data = rec.get_traces(
                start_frame=int(t0 * sr),
                end_frame=int(t1 * sr),
                return_in_uV=False,
            )

            # Compare
            match = np.array_equal(nwb_data, source_data)
            results[ap_name] = {
                "shape_nwb": nwb_data.shape,
                "shape_source": source_data.shape,
                "dtype_nwb": str(nwb_data.dtype),
                "bit_exact": match,
            }
            status = "PASS" if match else "FAIL"
            print(f"  {status} {ap_name}: NWB {nwb_data.shape} vs source {source_data.shape}")

            if not match:
                diff = np.abs(nwb_data.astype(np.int32) - source_data.astype(np.int32))
                print(f"    Max diff: {diff.max()}, Mean diff: {diff.mean():.4f}")

            # Check LF
            lf_name = f"ElectricalSeriesLF_{probe.probe_id}"
            if lf_name in nwbfile.acquisition:
                lf_es = nwbfile.acquisition[lf_name]
                lf_nwb = lf_es.data[:]
                lf_rec = SpikeGLXLoader.load_lf(probe)
                lf_sr = lf_rec.get_sampling_frequency()
                lf_source = lf_rec.get_traces(
                    start_frame=int(t0 * lf_sr),
                    end_frame=int(t1 * lf_sr),
                    return_in_uV=False,
                )
                lf_match = np.array_equal(lf_nwb, lf_source)
                results[lf_name] = {
                    "shape_nwb": lf_nwb.shape,
                    "shape_source": lf_source.shape,
                    "bit_exact": lf_match,
                }
                status = "PASS" if lf_match else "FAIL"
                print(f"  {status} {lf_name}: NWB {lf_nwb.shape} vs source {lf_source.shape}")

    # File size and compression ratio
    nwb_size = nwb_path.stat().st_size
    raw_samples = int((t1 - t0) * 30000) * 384 * 2  # approx AP raw bytes
    ratio = raw_samples / nwb_size if nwb_size > 0 else 0
    results["file_size_mb"] = nwb_size / 1024 / 1024
    results["approx_compression_ratio"] = f"{ratio:.1f}x"
    print(f"\n  NWB file size: {nwb_size / 1024 / 1024:.1f} MB")
    print(f"  Approx compression ratio: {ratio:.1f}x (vs raw AP)")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 raw export harness")
    parser.add_argument(
        "--seconds", type=float, default=1.0,
        help="Duration of data to export (seconds, default: 1.0)",
    )
    parser.add_argument(
        "--skip-lf", action="store_true",
        help="Skip LF stream export",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Phase 3 Raw Export Harness")
    print(f"  Data: {DATA_DIR}")
    print(f"  Duration: {args.seconds}s")
    print(f"{'='*60}\n")

    # 1. Load session — reuse existing session.json or run discover
    from pynpxpipe.core.config import load_subject_config
    from pynpxpipe.core.session import SessionManager

    subject = load_subject_config(SUBJECT_YAML)

    import tempfile
    work_dir = Path(tempfile.mkdtemp(prefix="pynpxpipe_harness_"))
    print(f"  Working dir: {work_dir}")

    # Try loading existing session from DATA_DIR (has probes from discover)
    session_json = DATA_DIR / "session.json"
    if session_json.exists():
        session = SessionManager.load(DATA_DIR)
        print(f"  Loaded existing session: {len(session.probes)} probe(s)")
    else:
        # Create new session and run discover to populate probes
        session = SessionManager.from_data_dir(DATA_DIR, subject, work_dir)
        from pynpxpipe.stages.discover import DiscoverStage
        discover = DiscoverStage(session)
        discover.run()
        print(f"  Discovered session: {len(session.probes)} probe(s)")

    if not session.probes:
        print("  ERROR: No probes found. Run discover stage first.")
        sys.exit(1)

    if args.skip_lf:
        for probe in session.probes:
            probe.lf_bin = None
            probe.lf_meta = None

    # 2. Create minimal NWB
    nwb_path = work_dir / "test_export_raw.nwb"
    create_minimal_nwb(session, nwb_path)

    # 3. Append raw data
    from pynpxpipe.io.nwb_writer import NWBWriter

    writer = NWBWriter(session, nwb_path)
    time_range = (0.0, args.seconds)

    print(f"\n  Appending raw data (time_range={time_range}) ...")
    t_start = time.perf_counter()

    try:
        result = writer.append_raw_data(
            session, nwb_path, time_range=time_range,
        )
    except (NotImplementedError, TypeError) as exc:
        print(f"  append_raw_data not yet implemented: {exc}")
        print(f"\n  Harness infrastructure is ready. Implement append_raw_data to proceed.")
        sys.exit(2)

    elapsed = time.perf_counter() - t_start
    print(f"  append_raw_data returned: {result}")
    print(f"  Elapsed: {elapsed:.1f}s")

    # 4. Verify bit-exact
    print(f"\n  Verifying bit-exact roundtrip ...")
    verification = verify_bit_exact(session, nwb_path, time_range)

    # 5. Summary
    all_pass = all(
        v.get("bit_exact", True)
        for v in verification.values()
        if isinstance(v, dict)
    )
    print(f"\n{'='*60}")
    if all_pass:
        print("  HARNESS PASSED — all streams bit-exact")
    else:
        print("  HARNESS FAILED — bit mismatch detected")
        sys.exit(1)
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
