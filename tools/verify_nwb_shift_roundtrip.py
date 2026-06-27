"""tools/verify_nwb_shift_roundtrip.py — real-data check of the §9 writer fix.

Round-trips the REAL 260330 imec1 (MSB) ``inter_sample_shift`` through the fixed
writer → NWB → reader and confirms phase_shift actually engages on the reloaded
recording. This is the "验证切片" for nwb_writer.md §9 / nwb_reader.md §10: unit
tests use synthetic shifts; here we prove real SpikeGLX shift values survive the
round-trip and that ``_preprocess_raw_recording`` applies phase_shift (the
property gate is hit and the traces actually change).

Reads only a short AP slice (fast on NAS). Writes a throwaway NWB under --out.

Usage:
    uv run python tools/verify_nwb_shift_roundtrip.py --out /tmp/shift_verify
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from pynpxpipe.core.config import load_pipeline_config
from pynpxpipe.core.session import ProbeInfo, Session, SessionID, SubjectConfig
from pynpxpipe.io.nwb_reader import NWBLoader
from pynpxpipe.io.nwb_writer import NWBWriter
from pynpxpipe.io.spikeglx import SpikeGLXLoader
from pynpxpipe.pipelines.nwb_rerun import _preprocess_raw_recording

RAW = Path(
    "/home/gongzhengxin/mnt_nas/260330_FLD_MSBV4/NPX_FLD260330_exp2_g1/NPX_FLD260330_exp2_g1_imec1"
)
AP_BIN = RAW / "NPX_FLD260330_exp2_g1_t0.imec1.ap.bin"
AP_META = RAW / "NPX_FLD260330_exp2_g1_t0.imec1.ap.meta"
PROBE_ID = "imec1"


def _mock_analyzer(n_units: int = 1, n_samples: int = 60, n_channels: int = 4) -> MagicMock:
    """Tiny mock SortingAnalyzer (geometry comes from raw, not from this)."""
    unit_ids = [f"u{i}" for i in range(n_units)]
    sorting = MagicMock()
    sorting.get_unit_ids.return_value = unit_ids
    sorting.get_unit_spike_train.return_value = np.array([0.1, 0.2, 0.5])
    templates = MagicMock()
    templates.get_templates.return_value = np.random.randn(n_units, n_samples, n_channels).astype(
        np.float32
    )
    locs = MagicMock()
    locs.get_data.return_value = np.zeros((n_units, 3))
    qm = MagicMock()
    qm.get_data.return_value = pd.DataFrame(
        {"isi_violation_ratio": [0.0] * n_units, "snr": [1.0] * n_units}, index=unit_ids
    )
    available = {"waveforms", "templates", "unit_locations", "quality_metrics"}
    an = MagicMock()
    an.sorting = sorting
    an.has_extension.side_effect = lambda n: n in available
    an.get_extension.side_effect = lambda n: {
        "templates": templates,
        "waveforms": templates,
        "unit_locations": locs,
        "quality_metrics": qm,
    }[n]
    return an


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/tmp/shift_verify"))
    parser.add_argument("--slice-sec", type=float, default=3.0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    nwb_path = args.out / "shift_roundtrip.nwb"
    if nwb_path.exists():
        nwb_path.unlink()

    probe = ProbeInfo(
        probe_id=PROBE_ID,
        ap_bin=AP_BIN,
        ap_meta=AP_META,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=384,
        probe_type="NP1.0",
        serial_number="unknown",
        target_area="MSB",
    )

    # 1) Real raw AP → real geometry + inter_sample_shift.
    raw_ap = SpikeGLXLoader.load_ap(probe)
    real_shift = np.asarray(raw_ap.get_property("inter_sample_shift"), dtype=float)
    real_geom = [(float(x), float(y)) for x, y in raw_ap.get_channel_locations()]
    print(f"[verify] real inter_sample_shift: n={len(real_shift)} first8={real_shift[:8].round(4)}")

    # 2) Write a tiny NWB through the FIXED writer.
    subject = SubjectConfig("Faladi", "verify", "Macaca mulatta", "U", "P0Y", "0kg")
    session = Session(
        session_dir=args.out,
        output_dir=args.out,
        subject=subject,
        bhv_file=args.out / "x.bhv2",
        session_id=SessionID(date="260330", subject="Faladi", experiment="nsd1w", region="MSB"),
        probe_plan={PROBE_ID: "MSB"},
        config=load_pipeline_config(),
        probes=[probe],
    )
    writer = NWBWriter(session, nwb_path)
    writer.create_file()
    writer.add_probe_data(
        probe,
        _mock_analyzer(),
        raw_channel_positions=real_geom,
        inter_sample_shift=real_shift,
    )
    writer.write()
    sr = raw_ap.get_sampling_frequency()
    writer.append_raw_data(
        session, nwb_path, time_range=(0.0, args.slice_sec), verify_policy="sample"
    )
    print(f"[verify] wrote NWB slice [0,{args.slice_sec}s] at fs={sr:.4f}")

    # 3) Reload and assert the shift is restored.
    rec = NWBLoader(nwb_path).load_recordings(stream_type="ap")[PROBE_ID].recording
    restored = rec.get_property("inter_sample_shift")
    assert restored is not None, "FAIL: inter_sample_shift not restored on reload"
    restored = np.asarray(restored, dtype=float)
    assert len(restored) == rec.get_num_channels(), "FAIL: shift length != n_channels"
    assert np.allclose(restored, real_shift[: len(restored)]), "FAIL: shift values changed"
    print(f"[verify] reload OK: inter_sample_shift restored, n={len(restored)}, matches real")

    # 4) Confirm phase_shift actually engages: with the property present the chain
    #    applies it; dropping the property skips it → traces must differ.
    cfg = load_pipeline_config()
    cfg.preprocess.motion_correction.method = None  # isolate phase_shift (skip dredge)
    assert "inter_sample_shift" in rec.get_property_keys(), "FAIL: property gate not set"
    pp_with = _preprocess_raw_recording(rec, cfg)

    rec_no = NWBLoader(nwb_path).load_recordings(stream_type="ap")[PROBE_ID].recording
    rec_no.delete_property("inter_sample_shift")
    pp_without = _preprocess_raw_recording(rec_no, cfg)

    t_with = pp_with.get_traces(start_frame=0, end_frame=300)
    t_without = pp_without.get_traces(start_frame=0, end_frame=300)
    differ = not np.allclose(t_with, t_without)
    print(
        f"[verify] phase_shift engaged: with vs without differ = {differ} "
        f"(max abs diff = {np.abs(t_with - t_without).max():.4f})"
    )
    assert differ, "FAIL: phase_shift did not change traces — gate not effective"
    print(
        "[verify] PASS — §9 writer fix round-trips real inter_sample_shift and phase_shift engages."
    )


if __name__ == "__main__":
    main()
